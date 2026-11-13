#Requires -Version 5.1
<#
.SYNOPSIS
    DataExtraction Enterprise Platform — Local Development Launcher
.DESCRIPTION
    Starts the FastAPI backend and Next.js frontend for local development.
    Prerequisites: Python 3.12+, Node.js 20+, PostgreSQL running, .env populated.
.EXAMPLE
    .\start.ps1
    .\start.ps1 -BackendPort 8000 -FrontendPort 3000
#>

[CmdletBinding()]
param(
    [int]    $BackendPort  = 8000,
    [int]    $FrontendPort = 3000,
    [switch] $NoFrontend,
    [switch] $NoBackend
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT     = $PSScriptRoot
$FRONTEND = Join-Path $ROOT "frontend"
$LOGS_DIR = Join-Path $ROOT "logs"

# ── Resolve Python ────────────────────────────────────────────────────────────
function Find-Python {
    # Priority 1: venv in repo root (created by bootstrap.ps1 or manually)
    $venvPy = Join-Path $ROOT ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }

    # Priority 2: python on PATH
    try {
        $found = (Get-Command python -ErrorAction Stop).Source
        $ver = & $found --version 2>&1
        if ($ver -match "Python 3\.(1[2-9]|[2-9]\d)") { return $found }
        Write-Warning "python on PATH is $ver — Python 3.12+ preferred."
        return $found
    } catch {}

    # Priority 3: common Windows install locations
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python313\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }

    throw "Python 3.12+ not found. Install it or create a .venv with: python -m venv .venv && .\.venv\Scripts\activate && pip install -r requirements.txt"
}

# ── Validate .env ─────────────────────────────────────────────────────────────
function Assert-DotEnv {
    $envFile = Join-Path $ROOT ".env"
    if (-not (Test-Path $envFile)) {
        Write-Warning ".env not found — copying from .env.example. Edit it before continuing."
        Copy-Item (Join-Path $ROOT ".env.example") $envFile
    }

    $content = Get-Content $envFile -Raw
    $required = @("POSTGRES_PASSWORD", "JWT_SECRET", "API_ADMIN_PASSWORD")
    $missing  = @()
    foreach ($key in $required) {
        if ($content -notmatch "^${key}=.+") { $missing += $key }
    }
    if ($missing.Count -gt 0) {
        Write-Host ""
        Write-Host "  [WARN] The following required env vars are not set in .env:" -ForegroundColor Yellow
        foreach ($k in $missing) { Write-Host "         $k" -ForegroundColor Yellow }
        Write-Host "  Edit .env and re-run this script." -ForegroundColor Yellow
        Write-Host ""
    }
}

# ── Main ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  DataExtraction Enterprise Platform — Local Dev Launcher" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Assert-DotEnv

$PYTHON = Find-Python
Write-Host "  Python  : $PYTHON" -ForegroundColor Gray
Write-Host "  Node    : $(node --version 2>$null || 'not found')" -ForegroundColor Gray
Write-Host ""

# Ensure logs directory exists
if (-not (Test-Path $LOGS_DIR)) {
    New-Item -ItemType Directory -Path $LOGS_DIR -Force | Out-Null
}

# ── Build PYTHONPATH ──────────────────────────────────────────────────────────
# Must include the repo root so `packages.*` imports resolve correctly,
# AND packages/infrastructure for any legacy standalone scripts that still
# use bare imports during the transition period.
$GmapsSrc = Join-Path $ROOT "packages\scrapers\google_maps\src"
$InfraDir = Join-Path $ROOT "packages\infrastructure"
$env:PYTHONPATH = "$ROOT;$InfraDir;$GmapsSrc"
$env:API_PORT = "$BackendPort"

$jobs = @()

# ── Backend ───────────────────────────────────────────────────────────────────
if (-not $NoBackend) {
    Write-Host "[1/2] Starting FastAPI backend on http://localhost:$BackendPort ..." -ForegroundColor Yellow
    $backendLog = Join-Path $LOGS_DIR "backend.log"
    $backendJob = Start-Job -Name "dex-backend" -ScriptBlock {
        param($root, $log, $py, $port, $infraDir, $gmapsSrc)
        $env:PYTHONPATH = "$root;$infraDir;$gmapsSrc"
        $env:API_PORT   = "$port"
        Set-Location $root
        # Use uvicorn directly with --reload-dir to restrict file watching to packages/api only
        & $py -X utf8 -m uvicorn packages.api.main:app `
            --host 0.0.0.0 --port $port `
            --reload --reload-dir "$root\packages\api" `
            --log-level info 2>&1 | Tee-Object -FilePath $log
    } -ArgumentList $ROOT, $backendLog, $PYTHON, $BackendPort, $InfraDir, $GmapsSrc
    $jobs += $backendJob
    Write-Host "  [OK] Backend starting (Job $($backendJob.Id)) — logs/backend.log" -ForegroundColor Green
}

# ── Frontend ──────────────────────────────────────────────────────────────────
if (-not $NoFrontend) {
    Write-Host ""
    Write-Host "[2/2] Starting Next.js frontend on http://localhost:$FrontendPort ..." -ForegroundColor Yellow

    # Ensure frontend .env.local points to the correct backend port
    $frontendEnv = Join-Path $FRONTEND ".env.local"
    $apiUrl = "http://localhost:${BackendPort}/api"
    if (Test-Path $frontendEnv) {
        $envContent = Get-Content $frontendEnv -Raw
        if ($envContent -notmatch [regex]::Escape("NEXT_PUBLIC_API_URL=$apiUrl")) {
            # Update the URL to match the actual backend port
            $envContent = $envContent -replace 'NEXT_PUBLIC_API_URL=http://localhost:\d+/api', "NEXT_PUBLIC_API_URL=$apiUrl"
            Set-Content $frontendEnv $envContent -NoNewline
            Write-Host "  [INFO] Updated frontend NEXT_PUBLIC_API_URL to $apiUrl" -ForegroundColor Gray
        }
    } else {
        "NEXT_PUBLIC_API_URL=$apiUrl`nNEXT_PUBLIC_APP_NAME=DataExtraction`n" | Set-Content $frontendEnv
        Write-Host "  [INFO] Created frontend .env.local with NEXT_PUBLIC_API_URL=$apiUrl" -ForegroundColor Gray
    }

    $frontendLog = Join-Path $LOGS_DIR "frontend.log"
    $frontendJob = Start-Job -Name "dex-frontend" -ScriptBlock {
        param($dir, $log, $port)
        Set-Location $dir
        $env:PORT = "$port"
        npm run dev -- --port $port 2>&1 | Tee-Object -FilePath $log
    } -ArgumentList $FRONTEND, $frontendLog, $FrontendPort
    $jobs += $frontendJob
    Write-Host "  [OK] Frontend starting (Job $($frontendJob.Id)) — logs/frontend.log" -ForegroundColor Green
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Services starting — allow 10-15s for full readiness" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Frontend   :  http://localhost:$FrontendPort" -ForegroundColor White
Write-Host "  Backend    :  http://localhost:$BackendPort" -ForegroundColor White
Write-Host "  API Docs   :  http://localhost:$BackendPort/api/docs" -ForegroundColor White
Write-Host ""

$adminEmail = if ($env:API_ADMIN_EMAIL) { $env:API_ADMIN_EMAIL } else { "admin@dataextraction.io" }
Write-Host "  Login Email: $adminEmail" -ForegroundColor Gray
Write-Host "  Password   : (set via API_ADMIN_PASSWORD in .env)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Press Ctrl+C to stop all services." -ForegroundColor DarkGray
Write-Host ""

# ── Log tail loop ─────────────────────────────────────────────────────────────
try {
    while ($true) {
        Start-Sleep -Seconds 3
        foreach ($job in $jobs) {
            Receive-Job $job -ErrorAction SilentlyContinue |
                ForEach-Object { Write-Host "[$($job.Name)] $_" -ForegroundColor DarkGray }
        }
        # Exit if all jobs stopped unexpectedly
        $running = $jobs | Where-Object { $_.State -eq "Running" }
        if ($jobs.Count -gt 0 -and $running.Count -eq 0) {
            Write-Host "All service jobs have stopped." -ForegroundColor Yellow
            break
        }
    }
} finally {
    Write-Host ""
    Write-Host "Stopping services..." -ForegroundColor Yellow
    $jobs | Stop-Job  -ErrorAction SilentlyContinue
    $jobs | Remove-Job -ErrorAction SilentlyContinue
    Write-Host "Done." -ForegroundColor Green
}
