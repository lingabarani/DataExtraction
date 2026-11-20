#Requires -Version 5.1
<#
.SYNOPSIS
    DataExtraction Enterprise Platform - Unified Local Development Launcher
.DESCRIPTION
    Starts the full enterprise stack with a single command:
      1. Validates PostgreSQL Database connection (localhost:5432)
      2. Ensures Temporal Dev Server is running (localhost:7233 & UI localhost:8233)
      3. Registers Temporal cron schedules from config/schedules.yaml
      4. Launches 8-Agent Temporal Worker Fleet supervisor (scripts/ops/start_all_workers.py)
      5. Launches Backend FastAPI Gateway (http://localhost:8000)
      6. Launches Frontend Next.js Dashboard (http://localhost:3000)
.EXAMPLE
    .\start.ps1
    .\start.ps1 -BackendPort 8000 -FrontendPort 3000
    .\start.ps1 -NoTemporal -NoWorkers
#>

[CmdletBinding()]
param(
    [int]    $BackendPort    = 8000,
    [int]    $FrontendPort   = 3000,
    [int]    $TemporalPort   = 7233,
    [int]    $TemporalUiPort = 8233,
    [switch] $NoTemporal,
    [switch] $NoWorkers,
    [switch] $NoFrontend,
    [switch] $NoBackend
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT     = $PSScriptRoot
$FRONTEND = Join-Path $ROOT "frontend"
$LOGS_DIR = Join-Path $ROOT "logs"
$DATA_DIR = Join-Path $ROOT "data"

# -- Utility: Fast TCP Socket Probe -------------------------------------------
function Test-TcpPort {
    param(
        [string]$HostName = "127.0.0.1",
        [int]$Port = 7233,
        [int]$TimeoutMs = 1000
    )
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async  = $client.BeginConnect($HostName, $Port, $null, $null)
        $ready  = $async.AsyncWaitHandle.WaitOne($TimeoutMs)
        $client.Close()
        return [bool]$ready
    } catch {
        return $false
    }
}

# -- Resolve Python ------------------------------------------------------------
function Find-Python {
    # Priority 1: venv in repo root (created by bootstrap.ps1 or manually)
    $venvPy = Join-Path $ROOT ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }

    # Priority 2: python on PATH
    try {
        $found = (Get-Command python -ErrorAction Stop).Source
        $ver = & $found --version 2>&1
        if ($ver -match "Python 3\.(1[2-9]|[2-9]\d)") { return $found }
        Write-Warning "python on PATH is $ver - Python 3.12+ preferred."
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

    throw 'Python 3.12+ not found. Install it or create a .venv with: python -m venv .venv; .\.venv\Scripts\activate; pip install -r requirements.txt'
}

# -- Resolve Temporal Binary ---------------------------------------------------
function Find-Temporal {
    $bin = Join-Path $ROOT "bin\temporal.exe"
    if (Test-Path $bin) { return $bin }
    $cmd = Get-Command temporal -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# -- Validate .env -------------------------------------------------------------
function Assert-DotEnv {
    $envFile = Join-Path $ROOT ".env"
    if (-not (Test-Path $envFile)) {
        Write-Warning ".env not found - copying from .env.example. Edit it before continuing."
        Copy-Item (Join-Path $ROOT ".env.example") $envFile
    }

    $content = Get-Content $envFile -Raw
    $required = @("POSTGRES_PASSWORD", "JWT_SECRET_KEY", "API_ADMIN_PASSWORD")
    $missing  = @()
    foreach ($key in $required) {
        if ($content -notmatch "(?m)^${key}=.+") { $missing += $key }
    }
    if ($missing.Count -gt 0) {
        Write-Host ""
        Write-Host "  [WARN] The following required env vars are not set in .env:" -ForegroundColor Yellow
        foreach ($k in $missing) { Write-Host "         $k" -ForegroundColor Yellow }
        Write-Host "  Edit .env and re-run this script." -ForegroundColor Yellow
        Write-Host ""
    }
}

# -- Validate PostgreSQL -------------------------------------------------------
function Assert-Postgres {
    param([string]$py)
    Write-Host "  [1/5] Checking PostgreSQL Database on localhost:5432..." -ForegroundColor Yellow
    $dbUp = Test-TcpPort -HostName "127.0.0.1" -Port 5432 -TimeoutMs 1000
    if (-not $dbUp) {
        Write-Host "        -> WARNING: PostgreSQL port 5432 is not reachable." -ForegroundColor Red
        Write-Host "           Please ensure PostgreSQL service is running." -ForegroundColor Yellow
        return $false
    }

    try {
        $env:PYTHONPATH = $ROOT
        $probe = & $py -c "
from packages.infrastructure.db_connector import get_connection, release_connection
conn = get_connection()
if conn:
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM master_dataextraction.organizations;')
        c = cur.fetchone()[0]
    release_connection(conn)
    print(f'OK:{c}')
else:
    print('FAIL')
" 2>$null
        if ($probe -match "OK:(\d+)") {
            Write-Host "        -> SUCCESS: PostgreSQL connected (Organizations: $($Matches[1]))" -ForegroundColor Green
            return $true
        }
    } catch {}

    Write-Host "        -> SUCCESS: PostgreSQL port 5432 is open and listening." -ForegroundColor Green
    return $true
}

# -- Start Temporal Server -----------------------------------------------------
function Start-TemporalServer {
    param(
        [string]$temporalBin,
        [int]$grpcPort,
        [int]$uiPort
    )
    Write-Host "  [2/5] Checking Temporal Orchestration Server..." -ForegroundColor Yellow
    if (Test-TcpPort -HostName "127.0.0.1" -Port $grpcPort -TimeoutMs 1000) {
        Write-Host "        -> SUCCESS: Temporal Server already active on 127.0.0.1:$grpcPort (UI: http://localhost:$uiPort)" -ForegroundColor Green
        return $null
    }

    if (-not $temporalBin) {
        Write-Host "        -> ERROR: Temporal binary not found (checked bin\temporal.exe and PATH)." -ForegroundColor Red
        Write-Host "           Workflows require Temporal on port $grpcPort." -ForegroundColor Yellow
        return $null
    }

    if (-not (Test-Path $DATA_DIR)) {
        New-Item -ItemType Directory -Path $DATA_DIR -Force | Out-Null
    }
    $dbFile = Join-Path $DATA_DIR "temporal.sqlite"
    $temporalLog = Join-Path $LOGS_DIR "temporal.log"
    $temporalErr = Join-Path $LOGS_DIR "temporal-err.log"

    Write-Host "        -> Spawning local Temporal dev server daemon (port $grpcPort, UI $uiPort)..." -ForegroundColor Gray
    $argsList = "server start-dev --namespace dataextraction --ip 127.0.0.1 --port $grpcPort --ui-port $uiPort --db-filename `"$dbFile`""

    $proc = Start-Process -FilePath $temporalBin -ArgumentList $argsList -PassThru -NoNewWindow -RedirectStandardOutput $temporalLog -RedirectStandardError $temporalErr

    # Wait up to 15 seconds for port 7233 to open
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-TcpPort -HostName "127.0.0.1" -Port $grpcPort -TimeoutMs 500) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }

    if ($ready) {
        Write-Host "        -> SUCCESS: Temporal Server ready on 127.0.0.1:$grpcPort (UI: http://localhost:$uiPort)" -ForegroundColor Green
    } else {
        Write-Host "        -> WARNING: Temporal server did not open port $grpcPort within 15 seconds (PID $($proc.Id))." -ForegroundColor Yellow
    }
    return $proc
}

# -- Register Temporal Schedules -----------------------------------------------
function Register-TemporalSchedules {
    param([string]$py)
    Write-Host "        -> Registering Temporal schedules from config/schedules.yaml..." -ForegroundColor Gray
    try {
        $env:PYTHONPATH = $ROOT
        $out = & $py -m packages.temporal.schedules.register_schedules 2>&1
        $matched = @($out | Select-String -Pattern "Registered schedule|already exists")
        $count = $matched.Count
        Write-Host "        -> SUCCESS: Temporal schedules registered ($count verified)." -ForegroundColor Green
    } catch {
        Write-Host "        -> WARNING: Schedule registration notice: $_" -ForegroundColor Yellow
    }
}

# -- Start Worker Supervisor ---------------------------------------------------
function Start-WorkerSupervisor {
    param([string]$py, [string]$infraDir, [string]$gmapsSrc)
    Write-Host "  [3/5] Starting 8-Agent Temporal Worker Supervisor Fleet..." -ForegroundColor Yellow
    $workerScript = Join-Path $ROOT "scripts\ops\start_all_workers.py"
    if (-not (Test-Path $workerScript)) {
        Write-Host "        -> WARNING: Supervisor script not found at $workerScript" -ForegroundColor Yellow
        return $null
    }

    $workersLog = Join-Path $LOGS_DIR "workers.log"
    $workerJob = Start-Job -Name "dex-workers" -ScriptBlock {
        param($root, $log, $py, $workerScript, $infraDir, $gmapsSrc)
        $env:PYTHONPATH = "$root;$infraDir;$gmapsSrc"
        Set-Location $root
        & $py -X utf8 $workerScript 2>&1 | Tee-Object -FilePath $log
    } -ArgumentList $ROOT, $workersLog, $py, $workerScript, $infraDir, $gmapsSrc

    Start-Sleep -Seconds 3
    if ($workerJob.State -ne "Running") {
        Write-Host "        -> WARNING: Worker supervisor job stopped unexpectedly. See logs/workers.log" -ForegroundColor Yellow
    } else {
        Write-Host "        -> SUCCESS: 8-Agent worker supervisor active (Job $($workerJob.Id)) - logs/workers.log" -ForegroundColor Green
    }
    return $workerJob
}

# ==============================================================================
# MAIN LAUNCHER SEQUENCE
# ==============================================================================

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   DATAEXTRACTION — ENTERPRISE B2B LEAD INTELLIGENCE PLATFORM        " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

Assert-DotEnv

$PYTHON = Find-Python
Write-Host "  Python    : $PYTHON" -ForegroundColor Gray
$nodeVer = try { (node --version 2>$null) } catch { "not found" }
if (-not $nodeVer) { $nodeVer = "not found" }
Write-Host "  Node      : $nodeVer" -ForegroundColor Gray

$TEMPORAL_BIN = Find-Temporal
if ($TEMPORAL_BIN) {
    Write-Host "  Temporal  : $TEMPORAL_BIN" -ForegroundColor Gray
} else {
    Write-Host "  Temporal  : not found in bin/ or PATH" -ForegroundColor Yellow
}
Write-Host ""

# Ensure logs and data directories exist
if (-not (Test-Path $LOGS_DIR)) { New-Item -ItemType Directory -Path $LOGS_DIR -Force | Out-Null }
if (-not (Test-Path $DATA_DIR)) { New-Item -ItemType Directory -Path $DATA_DIR -Force | Out-Null }

# Build PYTHONPATH
$GmapsSrc = Join-Path $ROOT "packages\scrapers\google_maps\src"
$InfraDir = Join-Path $ROOT "packages\infrastructure"
$env:PYTHONPATH = "$ROOT;$InfraDir;$GmapsSrc"
$env:API_PORT   = "$BackendPort"

$jobs = [System.Collections.Generic.List[System.Management.Automation.Job]]::new()
$spawnedTemporalProc = $null

# Step 1: PostgreSQL Check
Assert-Postgres -py $PYTHON | Out-Null

# Step 2: Temporal Dev Server
if (-not $NoTemporal) {
    $spawnedTemporalProc = Start-TemporalServer -temporalBin $TEMPORAL_BIN -grpcPort $TemporalPort -uiPort $TemporalUiPort
    if (Test-TcpPort -HostName "127.0.0.1" -Port $TemporalPort -TimeoutMs 1000) {
        Register-TemporalSchedules -py $PYTHON
    }
} else {
    Write-Host "  [2/5] Temporal startup skipped (-NoTemporal passed)." -ForegroundColor DarkGray
}

# Step 3: 8-Agent Worker Supervisor
if (-not $NoWorkers -and -not $NoTemporal) {
    $wJob = Start-WorkerSupervisor -py $PYTHON -infraDir $InfraDir -gmapsSrc $GmapsSrc
    if ($wJob) { $jobs.Add($wJob) }
} elseif ($NoWorkers) {
    Write-Host "  [3/5] Worker supervisor skipped (-NoWorkers passed)." -ForegroundColor DarkGray
}

# Step 4: FastAPI Backend Gateway
if (-not $NoBackend) {
    Write-Host "  [4/5] Starting FastAPI backend on http://localhost:$BackendPort ..." -ForegroundColor Yellow
    $backendLog = Join-Path $LOGS_DIR "backend.log"
    $backendJob = Start-Job -Name "dex-backend" -ScriptBlock {
        param($root, $log, $py, $port, $infraDir, $gmapsSrc)
        $env:PYTHONPATH = "$root;$infraDir;$gmapsSrc"
        $env:API_PORT   = "$port"
        Set-Location $root
        & $py -X utf8 -m uvicorn packages.api.main:app `
            --host 0.0.0.0 --port $port `
            --reload --reload-dir "$root\packages\api" `
            --log-level info 2>&1 | Tee-Object -FilePath $log
    } -ArgumentList $ROOT, $backendLog, $PYTHON, $BackendPort, $InfraDir, $GmapsSrc
    $jobs.Add($backendJob)
    Write-Host "        -> SUCCESS: Backend starting (Job $($backendJob.Id)) - logs/backend.log" -ForegroundColor Green
} else {
    Write-Host "  [4/5] Backend startup skipped (-NoBackend passed)." -ForegroundColor DarkGray
}

# Step 5: Next.js Frontend Dashboard
if (-not $NoFrontend) {
    Write-Host "  [5/5] Starting Next.js frontend on http://localhost:$FrontendPort ..." -ForegroundColor Yellow

    # Ensure frontend .env.local points to the correct backend port
    $frontendEnv = Join-Path $FRONTEND ".env.local"
    $apiUrl = "http://localhost:${BackendPort}/api"
    if (Test-Path $frontendEnv) {
        $envContent = Get-Content $frontendEnv -Raw
        if ($envContent -notmatch [regex]::Escape("NEXT_PUBLIC_API_URL=$apiUrl")) {
            $envContent = $envContent -replace 'NEXT_PUBLIC_API_URL=http://localhost:\d+/api', "NEXT_PUBLIC_API_URL=$apiUrl"
            Set-Content $frontendEnv $envContent -NoNewline
            Write-Host "        -> Updated frontend NEXT_PUBLIC_API_URL to $apiUrl" -ForegroundColor Gray
        }
    } else {
        "NEXT_PUBLIC_API_URL=$apiUrl`nNEXT_PUBLIC_APP_NAME=DataExtraction`n" | Set-Content $frontendEnv
        Write-Host "        -> Created frontend .env.local with NEXT_PUBLIC_API_URL=$apiUrl" -ForegroundColor Gray
    }

    $frontendLog = Join-Path $LOGS_DIR "frontend.log"
    $frontendJob = Start-Job -Name "dex-frontend" -ScriptBlock {
        param($dir, $log, $port)
        Set-Location $dir
        $env:PORT = "$port"
        npm run dev -- --port $port 2>&1 | Tee-Object -FilePath $log
    } -ArgumentList $FRONTEND, $frontendLog, $FrontendPort
    $jobs.Add($frontendJob)
    Write-Host "        -> SUCCESS: Frontend starting (Job $($frontendJob.Id)) - logs/frontend.log" -ForegroundColor Green
} else {
    Write-Host "  [5/5] Frontend startup skipped (-NoFrontend passed)." -ForegroundColor DarkGray
}

# -- Operational Summary -------------------------------------------------------
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   SERVICES ACTIVE & OPERATIONAL                                      " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  * Frontend UI : http://localhost:$FrontendPort" -ForegroundColor White
Write-Host "  * Backend API : http://localhost:$BackendPort" -ForegroundColor White
Write-Host "  * API Docs    : http://localhost:$BackendPort/api/docs" -ForegroundColor White
Write-Host "  * Temporal UI : http://localhost:$TemporalUiPort (gRPC: localhost:$TemporalPort)" -ForegroundColor White
Write-Host "  * Database    : PostgreSQL on localhost:5432/dataextraction" -ForegroundColor White
Write-Host "  * Worker Fleet: 8 Autonomous Agents Polling Dedicated Task Queues" -ForegroundColor White
Write-Host ""

$adminEmail = if ($env:API_ADMIN_EMAIL) { $env:API_ADMIN_EMAIL } else { "admin@dataextraction.io" }
Write-Host "  Login Email   : $adminEmail" -ForegroundColor Gray
Write-Host "  Password      : (configured via API_ADMIN_PASSWORD in .env)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Press Ctrl+C at any time to stop all services." -ForegroundColor DarkGray
Write-Host ""

if ($jobs.Count -eq 0 -and $null -eq $spawnedTemporalProc) {
    Write-Host "No services selected to start." -ForegroundColor Yellow
    return
}

# -- Log Tail Loop & Coordinated Teardown ---------------------------------------
try {
    while ($true) {
        Start-Sleep -Seconds 3
        foreach ($job in $jobs) {
            Receive-Job $job -ErrorAction SilentlyContinue |
                ForEach-Object { Write-Host "[$($job.Name)] $_" -ForegroundColor DarkGray }
        }
        $running = @($jobs | Where-Object { $_.State -eq "Running" })
        if ($jobs.Count -gt 0 -and $running.Count -eq 0) {
            Write-Host "All monitored service jobs have stopped." -ForegroundColor Yellow
            break
        }
    }
} finally {
    Write-Host ""
    Write-Host "Stopping all platform services cleanly..." -ForegroundColor Yellow

    # Stop PowerShell background jobs
    if ($jobs.Count -gt 0) {
        $jobs | Stop-Job -ErrorAction SilentlyContinue
        $jobs | Remove-Job -ErrorAction SilentlyContinue
    }

    # Stop spawned Temporal dev server if launched by this script
    if ($spawnedTemporalProc -and -not $spawnedTemporalProc.HasExited) {
        Write-Host "  Stopping Temporal Server daemon (PID $($spawnedTemporalProc.Id))..." -ForegroundColor Gray
        Stop-Process -Id $spawnedTemporalProc.Id -Force -ErrorAction SilentlyContinue
    }

    Write-Host "All platform services stopped. Goodbye!" -ForegroundColor Green
}
