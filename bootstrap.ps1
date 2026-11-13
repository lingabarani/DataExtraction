#Requires -Version 5.1
<#
.SYNOPSIS
    DataExtraction Enterprise Platform — One-Shot Local Dev Bootstrap
.DESCRIPTION
    Idempotent setup script that:
      1. Validates prerequisites (Python 3.12+, Node 20+, Docker)
      2. Creates a Python virtual environment if one does not exist
      3. Installs Python and Node dependencies
      4. Copies .env.example → .env if .env is missing, then prompts for required secrets
      5. Waits for PostgreSQL, then runs DB bootstrap SQL + migration runner
      6. Optionally starts Temporal dev server and creates the namespace
      7. Writes frontend/.env.local with the correct API URL
      8. Prints a final readiness summary

    Run once after cloning, then use start.ps1 for day-to-day development.
.EXAMPLE
    .\bootstrap.ps1
    .\bootstrap.ps1 -SkipDocker -SkipTemporal
#>

[CmdletBinding()]
param(
    [switch] $SkipDocker,
    [switch] $SkipTemporal,
    [switch] $SkipDeps,
    [int]    $BackendPort = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = $PSScriptRoot

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "  ► $msg" -ForegroundColor Cyan
}

function Write-OK([string]$msg)   { Write-Host "    [✓] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "    [!] $msg" -ForegroundColor Yellow }
function Write-Fail([string]$msg) { Write-Host "    [✗] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  DataExtraction Enterprise Platform — Bootstrap" -ForegroundColor Cyan
Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor Cyan

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
Write-Step "Checking prerequisites"

# Python
try {
    $pyVer = & python --version 2>&1
    if ($pyVer -match "Python 3\.(1[2-9]|[2-9]\d)") {
        Write-OK "Python: $pyVer"
        $PYTHON = "python"
    } else {
        Write-Warn "$pyVer found — Python 3.12+ recommended."
        $PYTHON = "python"
    }
} catch {
    Write-Fail "Python not found. Install Python 3.12+ from https://python.org"
    exit 1
}

# Node
try {
    $nodeVer = & node --version 2>&1
    Write-OK "Node.js: $nodeVer"
} catch {
    Write-Warn "Node.js not found. Install from https://nodejs.org (required for frontend)."
}

# Docker (optional check)
if (-not $SkipDocker) {
    try {
        $dockerVer = & docker --version 2>&1
        Write-OK "Docker: $dockerVer"
    } catch {
        Write-Warn "Docker not found — Docker stack will not be available. Install Docker Desktop."
    }
}

# ── 2. Virtual environment ────────────────────────────────────────────────────
Write-Step "Setting up Python virtual environment"

$venvPath = Join-Path $ROOT ".venv"
if (-not (Test-Path (Join-Path $venvPath "Scripts\python.exe"))) {
    Write-Host "    Creating .venv ..." -ForegroundColor Gray
    & $PYTHON -m venv $venvPath
    Write-OK "Virtual environment created: .venv"
} else {
    Write-OK "Virtual environment already exists: .venv"
}

$VENV_PY = Join-Path $venvPath "Scripts\python.exe"
$VENV_PIP = Join-Path $venvPath "Scripts\pip.exe"

# ── 3. Install Python dependencies ───────────────────────────────────────────
if (-not $SkipDeps) {
    Write-Step "Installing Python dependencies"
    & $VENV_PIP install --upgrade pip --quiet
    & $VENV_PIP install -r (Join-Path $ROOT "requirements.txt") --quiet
    Write-OK "Python dependencies installed."

    Write-Step "Installing Node.js dependencies (frontend)"
    Push-Location (Join-Path $ROOT "frontend")
    try {
        & npm ci --prefer-offline 2>&1 | Out-Null
        Write-OK "Node.js dependencies installed."
    } catch {
        Write-Warn "npm ci failed — try running: cd frontend && npm install"
    } finally {
        Pop-Location
    }
}

# ── 4. Environment configuration ──────────────────────────────────────────────
Write-Step "Configuring environment"

$envFile    = Join-Path $ROOT ".env"
$envExample = Join-Path $ROOT ".env.example"

if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Warn ".env created from .env.example — please set required secrets before continuing."
    } else {
        Write-Fail ".env.example not found. Cannot create .env."
        exit 1
    }
}

# Check required secrets
function Test-EnvValue([string]$key, [string[]]$badValues) {
    $content = Get-Content $envFile -Raw
    if ($content -match "^${key}=(.+)$") {
        $val = $Matches[1].Trim()
        if ($val -in $badValues -or $val -eq "") { return $false }
        return $true
    }
    return $false
}

$needsUpdate = $false
$required = @{
    "POSTGRES_PASSWORD"  = @("change_me_before_running", "")
    "JWT_SECRET"         = @("change_me_min_64_random_characters_never_commit_this_value", "")
    "API_ADMIN_PASSWORD" = @("change_me_strong_admin_password", "")
}

foreach ($key in $required.Keys) {
    if (-not (Test-EnvValue $key $required[$key])) {
        Write-Warn "${key} needs to be set in .env"
        $needsUpdate = $true
    }
}

if ($needsUpdate) {
    Write-Host ""
    Write-Host "    Please edit .env and set the required values, then re-run bootstrap.ps1." -ForegroundColor Yellow
    Write-Host "    Tip — generate JWT_SECRET with:" -ForegroundColor Gray
    Write-Host "      python -c `"import secrets; print(secrets.token_hex(32))`"" -ForegroundColor Gray
    Write-Host ""
    $continue = Read-Host "    Continue anyway? (y/N)"
    if ($continue -notmatch "^[Yy]") { exit 0 }
}

# Write frontend .env.local
$frontendEnv = Join-Path $ROOT "frontend\.env.local"
$apiUrl = "http://localhost:${BackendPort}/api"
"NEXT_PUBLIC_API_URL=${apiUrl}`nNEXT_PUBLIC_APP_NAME=DataExtraction`n" | Set-Content $frontendEnv
Write-OK "frontend/.env.local → NEXT_PUBLIC_API_URL=${apiUrl}"

# ── 5. Database bootstrap ─────────────────────────────────────────────────────
Write-Step "Bootstrapping database"

# Load env vars from .env for DB connection
$envContent = Get-Content $envFile
foreach ($line in $envContent) {
    if ($line -match "^([A-Z_][A-Z0-9_]*)=(.*)$") {
        $k = $Matches[1]; $v = $Matches[2].Trim('"').Trim("'")
        if (-not [System.Environment]::GetEnvironmentVariable($k)) {
            [System.Environment]::SetEnvironmentVariable($k, $v, "Process")
        }
    }
}

$dbHost = $env:POSTGRES_HOST ?? "localhost"
$dbPort = $env:POSTGRES_PORT ?? "5432"
$dbName = $env:POSTGRES_DB   ?? "dataextraction"
$dbUser = $env:POSTGRES_USER ?? "dex_user"
$dbPass = $env:POSTGRES_PASSWORD ?? ""

# Test DB connectivity
try {
    $testScript = @"
import psycopg2, os, sys
try:
    c = psycopg2.connect(host='$dbHost', port=$dbPort, dbname='$dbName', user='$dbUser', password='$dbPass', connect_timeout=5)
    c.close()
    print('OK')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
"@
    $result = & $VENV_PY -c $testScript 2>&1
    if ($result -eq "OK") {
        Write-OK "PostgreSQL connection verified: ${dbHost}:${dbPort}/${dbName}"
    } else {
        Write-Warn "Cannot connect to PostgreSQL: $result"
        Write-Warn "Make sure PostgreSQL is running and POSTGRES_PASSWORD is correct in .env"
        $skipDb = $true
    }
} catch {
    Write-Warn "psycopg2 not available yet — skipping DB bootstrap."
    $skipDb = $true
}

if (-not $skipDb) {
    # Run bootstrap SQL
    $bootstrapSql = Join-Path $ROOT "packages\infrastructure\bootstrap_db.sql"
    try {
        $env:PGPASSWORD = $dbPass
        $psqlResult = & psql -h $dbHost -p $dbPort -U $dbUser -d $dbName -f $bootstrapSql 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-OK "Database bootstrap SQL applied."
        } else {
            Write-Warn "psql not found or bootstrap failed — running via Python psycopg2 instead."
            $pyBootstrap = @"
import psycopg2, pathlib
sql = pathlib.Path('packages/infrastructure/bootstrap_db.sql').read_text(encoding='utf-8')
conn = psycopg2.connect(host='$dbHost', port=$dbPort, dbname='$dbName', user='$dbUser', password='$dbPass')
conn.autocommit = True
conn.cursor().execute(sql)
conn.close()
print('Bootstrap SQL applied via psycopg2.')
"@
            & $VENV_PY -c $pyBootstrap
            Write-OK "Database bootstrap SQL applied via psycopg2."
        }
    } catch {
        Write-Warn "Bootstrap SQL failed: $_"
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }

    # Run Python migration runner
    try {
        $env:PYTHONPATH = "$ROOT"
        & $VENV_PY -m packages.infrastructure.migration_manager 2>&1 |
            ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        Write-OK "Database migrations applied."
    } catch {
        Write-Warn "Migration runner error: $_"
    }
}

# ── 6. Temporal namespace ─────────────────────────────────────────────────────
if (-not $SkipTemporal) {
    Write-Step "Checking Temporal"
    $temporalHost = $env:TEMPORAL_HOST ?? "localhost:7233"
    $temporalNs   = $env:TEMPORAL_NAMESPACE ?? "dataextraction"

    # Quick TCP check
    try {
        $parts = $temporalHost.Split(":")
        $sock  = New-Object System.Net.Sockets.TcpClient
        $conn  = $sock.BeginConnect($parts[0], [int]$parts[1], $null, $null)
        $ok    = $conn.AsyncWaitHandle.WaitOne(1000)
        $sock.Close()
        if ($ok) {
            Write-OK "Temporal server reachable at $temporalHost"
            # Create namespace (idempotent)
            try {
                temporal operator namespace create $temporalNs 2>&1 | Out-Null
                Write-OK "Temporal namespace '$temporalNs' ready."
            } catch {
                Write-Warn "Could not create Temporal namespace (may already exist): $_"
            }
        } else {
            Write-Warn "Temporal not reachable at $temporalHost"
            Write-Warn "Start it with: temporal server start-dev --port 7233"
            Write-Warn "Then re-run: temporal operator namespace create $temporalNs"
        }
    } catch {
        Write-Warn "Could not check Temporal: $_"
    }
}

# ── 7. Final summary ──────────────────────────────────────────────────────────
Write-Host ""
Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Bootstrap complete!" -ForegroundColor Green
Write-Host "════════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Start local dev:           .\start.ps1" -ForegroundColor White
Write-Host "  Start Docker stack:        docker compose -f infra/docker-compose.yml --profile cpu up -d" -ForegroundColor White
Write-Host ""
Write-Host "  Frontend :  http://localhost:3000" -ForegroundColor Gray
Write-Host "  Backend  :  http://localhost:${BackendPort}" -ForegroundColor Gray
Write-Host "  API Docs :  http://localhost:${BackendPort}/api/docs" -ForegroundColor Gray
Write-Host ""
Write-Host "  Next steps if you haven't already:" -ForegroundColor DarkGray
Write-Host "    1. Edit .env — set POSTGRES_PASSWORD, JWT_SECRET, API_ADMIN_PASSWORD" -ForegroundColor DarkGray
Write-Host "    2. .\start.ps1" -ForegroundColor DarkGray
Write-Host ""
