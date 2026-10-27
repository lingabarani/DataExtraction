# DataExtraction Unified Platform — Start Both Backend and Frontend
# Usage: .\start.ps1

Set-StrictMode -Off
$ErrorActionPreference = "Continue"

$ROOT     = $PSScriptRoot
$BACKEND  = Join-Path $ROOT "packages\api"
$FRONTEND = Join-Path $ROOT "packages\frontend"
$LOGS_DIR = Join-Path $ROOT "logs"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  DataExtraction Enterprise Platform - Starting Services" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Resolve Python Environment
$PYTHON = "D:\Data Scraping Project POC\OneExtraction\.venv\Scripts\python.exe"
if (Test-Path (Join-Path $ROOT ".venv\Scripts\python.exe")) {
    $PYTHON = Join-Path $ROOT ".venv\Scripts\python.exe"
} elseif (-not (Test-Path $PYTHON)) {
    $PYTHON = "python"
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Program Files\Python312\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $PYTHON = $c
            break
        }
    }
}
Write-Host "  Using Python: $PYTHON" -ForegroundColor Gray

# Ensure logs directory exists
if (-not (Test-Path $LOGS_DIR)) {
    New-Item -ItemType Directory -Path $LOGS_DIR -Force | Out-Null
}

# Set Monorepo PYTHONPATH
$GmapsSrc = Join-Path $ROOT "packages\scrapers\google_maps\src"
$env:PYTHONPATH = "$GmapsSrc;$ROOT"

# 2. Start FastAPI Backend
Write-Host ""
Write-Host "[1/2] Starting FastAPI Backend on http://localhost:3001 ..." -ForegroundColor Yellow

$backendLog = Join-Path $LOGS_DIR "backend.log"
$backendJob = Start-Job -ScriptBlock {
    param($dir, $log, $pyCmd, $root)
    Set-Location $dir
    $env:PYTHONPATH = "$root\packages\scrapers\google_maps\src;$root"
    & $pyCmd -X utf8 api_server.py 2>&1 | Tee-Object -FilePath $log
} -ArgumentList $BACKEND, $backendLog, $PYTHON, $ROOT

Write-Host "  [OK] Backend starting (Job ID: $($backendJob.Id)) - log: logs/backend.log" -ForegroundColor Green

# 3. Start Next.js Frontend
Write-Host ""
Write-Host "[2/2] Starting Next.js Frontend on http://localhost:3000 ..." -ForegroundColor Yellow

$frontendLog = Join-Path $LOGS_DIR "frontend.log"
$frontendJob = Start-Job -ScriptBlock {
    param($dir, $log)
    Set-Location $dir
    npm run dev 2>&1 | Tee-Object -FilePath $log
} -ArgumentList $FRONTEND, $frontendLog

Write-Host "  [OK] Frontend starting (Job ID: $($frontendJob.Id)) - log: logs/frontend.log" -ForegroundColor Green

# Summary & Credentials
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  DataExtraction Platform is Running!" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Web Console :  http://localhost:3000" -ForegroundColor White
Write-Host "  Pipelines   :  http://localhost:3000/pipelines" -ForegroundColor White
Write-Host "  AI Agents   :  http://localhost:3000/agents" -ForegroundColor White
Write-Host "  Schedules   :  http://localhost:3000/schedules" -ForegroundColor White
Write-Host "  Backend API :  http://localhost:3001/api" -ForegroundColor White
Write-Host "  API Docs    :  http://localhost:3001/api/docs" -ForegroundColor White
Write-Host ""

$adminEmail = if ($env:API_ADMIN_EMAIL) { $env:API_ADMIN_EMAIL } else { "admin@oneextraction.io" }
$adminPassInfo = if ($env:API_ADMIN_PASSWORD) { "(Configured via API_ADMIN_PASSWORD)" } else { "admin123 (Development default)" }

Write-Host "  Login Credentials:" -ForegroundColor White
Write-Host "    Email    :  $adminEmail" -ForegroundColor Gray
Write-Host "    Password :  $adminPassInfo" -ForegroundColor Gray
Write-Host ""
Write-Host "  Press Ctrl+C to stop all services." -ForegroundColor DarkGray
Write-Host ""

try {
    while ($true) {
        Start-Sleep -Seconds 3
        Receive-Job $backendJob  2>$null | ForEach-Object { Write-Host "[API] $_" -ForegroundColor DarkGray }
        Receive-Job $frontendJob 2>$null | ForEach-Object { Write-Host "[UI]  $_" -ForegroundColor DarkGray }
    }
} finally {
    Write-Host ""
    Write-Host "Stopping DataExtraction services..." -ForegroundColor Yellow
    Stop-Job  $backendJob,  $frontendJob  2>$null
    Remove-Job $backendJob, $frontendJob  2>$null
    Write-Host "All services stopped." -ForegroundColor Green
}

