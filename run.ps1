#Requires -Version 5.1
<#
.SYNOPSIS
    Single-command local development launcher for DataExtraction Platform.
.DESCRIPTION
    Starts FastAPI backend + Next.js frontend with:
      - Non-blocking background DB bootstrap (does NOT block Python startup)
      - Automated migration runner (bootstrap_db.sql → migration_manager → migrate_schema)
      - --reload-dir restricted to packages/api only (prevents infinite reload loops)
      - Environment-aware settings (dev vs production)

    Prerequisites:
      ✓ Python 3.12+  (pip packages installed or .venv present)
      ✓ Node.js 20+   (frontend/node_modules present)
      ✓ PostgreSQL running on port 5432
      ✓ .env populated (POSTGRES_PASSWORD, JWT_SECRET, API_ADMIN_PASSWORD)

    Usage:
      .\run.ps1
      .\run.ps1 -SkipMigrations   # skip DB bootstrap/migrations if already done
      .\run.ps1 -BackendPort 3001  # run backend on a custom port
#>
[CmdletBinding()]
param(
    [int]    $BackendPort    = 8000,
    [int]    $FrontendPort   = 3000,
    [switch] $SkipMigrations,
    [switch] $NoFrontend,
    [switch] $NoBackend
)

$ErrorActionPreference = "Continue"
$ROOT = $PSScriptRoot

# ── Resolve Python ────────────────────────────────────────────────────────────
$PYTHON = "python"
foreach ($candidate in @(
    "$ROOT\.venv\Scripts\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
)) {
    if (Test-Path $candidate) { $PYTHON = $candidate; break }
}

# ── Build PYTHONPATH ──────────────────────────────────────────────────────────
# Repo root must be first so `packages.*` imports resolve.
# packages/infrastructure added for legacy standalone scripts.
$InfraDir = "$ROOT\packages\infrastructure"
$GmapsSrc = "$ROOT\packages\scrapers\google_maps\src"
$env:PYTHONPATH = "$ROOT;$InfraDir;$GmapsSrc"
$env:API_PORT   = "$BackendPort"

# ── Load .env into current process ───────────────────────────────────────────
if (Test-Path "$ROOT\.env") {
    Get-Content "$ROOT\.env" | Where-Object { $_ -match "^[A-Z_]+=\S" } | ForEach-Object {
        $parts = $_ -split "=", 2
        $key   = $parts[0]
        $val   = $parts[1].Trim('"').Trim("'")
        # Only set if not already in environment (allow overrides from shell)
        if (-not [Environment]::GetEnvironmentVariable($key)) {
            [Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
} else {
    Write-Warning ".env not found — copy .env.example to .env and fill in secrets before running."
}

# Sync frontend .env.local to match the backend port
$frontendEnv = "$ROOT\frontend\.env.local"
"NEXT_PUBLIC_API_URL=http://localhost:${BackendPort}/api`nNEXT_PUBLIC_APP_NAME=DataExtraction`n" |
    Set-Content $frontendEnv

# ── Ensure logs dir ───────────────────────────────────────────────────────────
if (-not (Test-Path "$ROOT\logs")) { New-Item -ItemType Directory "$ROOT\logs" | Out-Null }

# ── Banner ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "   DataExtraction Enterprise Platform — Local Dev" -ForegroundColor Cyan
Write-Host "  ══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Python  : $PYTHON" -ForegroundColor DarkGray
Write-Host "  Node    : $(node --version 2>$null)" -ForegroundColor DarkGray
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: DB bootstrap + migrations (runs as a BACKGROUND job — does NOT block
#          the backend from starting). The backend's lifespan handler will retry
#          the connection pool until PostgreSQL is available.
# ═══════════════════════════════════════════════════════════════════════════════
if (-not $SkipMigrations) {
    Write-Host "  [1/3] Running DB bootstrap & migrations (background)..." -ForegroundColor Cyan

    $migrateJob = Start-Job -Name "dex-migrate" -ScriptBlock {
        param($root, $py, $infraDir)
        $env:PYTHONPATH = "$root;$infraDir"

        # Load .env
        if (Test-Path "$root\.env") {
            Get-Content "$root\.env" | Where-Object { $_ -match "^[A-Z_]+=\S" } | ForEach-Object {
                $p = $_ -split "=", 2
                [Environment]::SetEnvironmentVariable($p[0], $p[1].Trim('"').Trim("'"), "Process")
            }
        }

        # ── Wait for PostgreSQL to be ready (up to 30s) ──────────────────────
        $dbHost = if ($env:POSTGRES_HOST) { $env:POSTGRES_HOST } else { "localhost" }
        $dbPort = if ($env:POSTGRES_PORT) { [int]$env:POSTGRES_PORT } else { 5432 }
        $ready  = $false
        for ($i = 0; $i -lt 30; $i++) {
            try {
                $sock = New-Object System.Net.Sockets.TcpClient
                $conn = $sock.BeginConnect($dbHost, $dbPort, $null, $null)
                $ok   = $conn.AsyncWaitHandle.WaitOne(1000)
                $sock.Close()
                if ($ok) { $ready = $true; break }
            } catch {}
            Start-Sleep -Seconds 1
        }
        if (-not $ready) {
            Write-Host "[MIGRATE] PostgreSQL not reachable at ${dbHost}:${dbPort} after 30s — skipping migrations." -ForegroundColor Yellow
            return
        }
        Write-Host "[MIGRATE] PostgreSQL ready. Applying bootstrap SQL..." -ForegroundColor DarkGray

        # ── Step A: Bootstrap SQL (idempotent base schema) ───────────────────
        $dbUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "dex_user" }
        $dbPass = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "" }
        $dbName = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "dataextraction" }

        $result = & $py -X utf8 -c @"
import sys, os
sys.path.insert(0,'$root')
os.environ.setdefault('POSTGRES_HOST','$dbHost')
os.environ.setdefault('POSTGRES_PORT','$dbPort')
os.environ.setdefault('POSTGRES_USER','$dbUser')
os.environ.setdefault('POSTGRES_DB','$dbName')
os.environ['POSTGRES_PASSWORD'] = '$dbPass'
try:
    import psycopg2
    conn = psycopg2.connect(host='$dbHost',port=$dbPort,dbname='$dbName',user='$dbUser',password='$dbPass',connect_timeout=5)
    conn.autocommit=True
    sql = open(r'$root\packages\infrastructure\bootstrap_db.sql',encoding='utf-8').read()
    conn.cursor().execute(sql)
    conn.close()
    print('bootstrap: OK')
except Exception as e:
    print(f'bootstrap: ERROR ({e})', file=sys.stderr)
    sys.exit(1)
"@ 2>&1
        Write-Host "[MIGRATE] $result" -ForegroundColor $(if ($LASTEXITCODE -eq 0) { "DarkGray" } else { "Red" })

        # ── Step B: Numbered SQL migrations 001-012 ───────────────────────────
        Write-Host "[MIGRATE] Applying numbered migrations (001-012)..." -ForegroundColor DarkGray
        $migResult = & $py -X utf8 -m packages.infrastructure.migration_manager 2>&1
        if ($LASTEXITCODE -eq 0) {
            $migResult | Select-Object -Last 5 | ForEach-Object { Write-Host "[MIGRATE] $_" -ForegroundColor DarkGray }
        } else {
            $migResult | ForEach-Object { Write-Host "[MIGRATE ERROR] $_" -ForegroundColor Red }
        }

        # ── Step C: Python column-addition migrations ─────────────────────────
        Write-Host "[MIGRATE] Applying Python schema additions..." -ForegroundColor DarkGray
        Set-Location "$root\packages\infrastructure"
        $schResult = & $py -X utf8 migrate_schema.py 2>&1
        if ($LASTEXITCODE -eq 0) {
            $schResult | Select-Object -Last 5 | ForEach-Object { Write-Host "[MIGRATE] $_" -ForegroundColor DarkGray }
        } else {
            $schResult | ForEach-Object { Write-Host "[MIGRATE ERROR] $_" -ForegroundColor Red }
        }

        Write-Host "[MIGRATE] Migration steps finished." -ForegroundColor Green

    } -ArgumentList $ROOT, $PYTHON, $InfraDir

    Write-Host "  Migrations running in background (Job $($migrateJob.Id))" -ForegroundColor Green
} else {
    Write-Host "  [1/3] Skipping DB bootstrap/migrations (-SkipMigrations flag set)." -ForegroundColor DarkGray
}

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: FastAPI Backend
# --reload-dir restricted to packages/api so watchfiles only watches the API
# source, not the entire 1,000+ file repo. This prevents:
#   - Infinite reload loops when log files or SQLite DB files are written
#   - 3-8 second reload cycles caused by watching all scraper/agent packages
# ═══════════════════════════════════════════════════════════════════════════════
if (-not $NoBackend) {
    Write-Host ""
    Write-Host "  [2/3] Starting FastAPI backend on http://localhost:${BackendPort} ..." -ForegroundColor Cyan

    $backendJob = Start-Job -Name "dex-api" -ScriptBlock {
        param($root, $py, $infraDir, $gmapsSrc, $port)
        $env:PYTHONPATH = "$root;$infraDir;$gmapsSrc"
        $env:API_PORT   = "$port"
        if (Test-Path "$root\.env") {
            Get-Content "$root\.env" | Where-Object { $_ -match "^[A-Z_]+=\S" } | ForEach-Object {
                $p = $_ -split "=", 2
                [Environment]::SetEnvironmentVariable($p[0], $p[1].Trim('"').Trim("'"), "Process")
            }
        }
        Set-Location $root
        # --reload-dir packages/api  → watch only the API package, NOT the whole repo
        & $py -X utf8 -m uvicorn packages.api.main:app `
            --host 0.0.0.0 `
            --port $port `
            --reload `
            --reload-dir "$root\packages\api" `
            --log-level info 2>&1

    } -ArgumentList $ROOT, $PYTHON, $InfraDir, $GmapsSrc, $BackendPort

    # Poll healthz for up to 15s
    $backendReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        Receive-Job $backendJob -ErrorAction SilentlyContinue |
            ForEach-Object { if ($_ -match "startup complete|pool init|running on") { Write-Host "  [API] $_" -ForegroundColor DarkGray } }
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:${BackendPort}/healthz" -TimeoutSec 1 -ErrorAction Stop
            if ($r.StatusCode -eq 200) { $backendReady = $true; break }
        } catch {}
    }

    if ($backendReady) {
        Write-Host "  Backend ready → http://localhost:${BackendPort}/api/docs" -ForegroundColor Green
    } else {
        Write-Host "  Backend starting (may take a few more seconds)..." -ForegroundColor Yellow
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: Next.js Frontend
# ═══════════════════════════════════════════════════════════════════════════════
$frontendJob = $null
if (-not $NoFrontend) {
    Write-Host ""
    Write-Host "  [3/3] Starting Next.js frontend on http://localhost:${FrontendPort} ..." -ForegroundColor Cyan

    $frontendJob = Start-Job -Name "dex-web" -ScriptBlock {
        param($dir, $port)
        Set-Location $dir
        & npm run dev -- --port $port 2>&1
    } -ArgumentList "$ROOT\frontend", $FrontendPort

    Write-Host "  Frontend starting (Job $($frontendJob.Id))..." -ForegroundColor Green
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "   Platform is running!" -ForegroundColor Cyan
Write-Host "  ══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "   Dashboard  →  http://localhost:${FrontendPort}/dashboard" -ForegroundColor White
Write-Host "   API Docs   →  http://localhost:${BackendPort}/api/docs" -ForegroundColor White
Write-Host "   Health     →  http://localhost:${BackendPort}/healthz" -ForegroundColor White
Write-Host ""
$authReq = $env:AUTH_REQUIRED; if (-not $authReq) { $authReq = "true" }
if ($authReq.ToLower() -eq "false") {
    Write-Host "   Auth Mode  :  Local Operator (AUTH_REQUIRED=false)" -ForegroundColor DarkGray
} else {
    Write-Host "   Auth Mode  :  Strict JWT Bearer (AUTH_REQUIRED=true)" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "   Press Ctrl+C to stop all services." -ForegroundColor DarkGray
Write-Host ""

# ── Log loop ──────────────────────────────────────────────────────────────────
$allJobs = @()
if ($backendJob)   { $allJobs += $backendJob }
if ($frontendJob)  { $allJobs += $frontendJob }
if (-not $SkipMigrations -and $migrateJob) { $allJobs += $migrateJob }

try {
    while ($true) {
        Start-Sleep -Seconds 2
        foreach ($job in $allJobs) {
            Receive-Job $job -ErrorAction SilentlyContinue |
                ForEach-Object { if ($_) { Write-Host "[$($job.Name)] $_" -ForegroundColor DarkGray } }
        }
    }
} finally {
    Write-Host ""
    Write-Host "  Stopping all services..." -ForegroundColor Yellow
    $allJobs | Stop-Job  -ErrorAction SilentlyContinue
    $allJobs | Remove-Job -ErrorAction SilentlyContinue
    Write-Host "  All services stopped." -ForegroundColor Green
}
