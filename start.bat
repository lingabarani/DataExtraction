@echo off
title DataExtraction Platform
cd /d "%~dp0"
echo ======================================================================
echo   DataExtraction Enterprise Platform — Starting Services
echo ======================================================================
echo.
echo   Preferred: use start.ps1 for the full-featured launcher.
echo   Fallback:  using start.py (basic launcher)
echo.

:: Resolve Python — prefer .venv in repo root
set PYTHON=python
if exist "%~dp0.venv\Scripts\python.exe" (
    set PYTHON="%~dp0.venv\Scripts\python.exe"
)

:: Set PYTHONPATH so packages.* imports resolve correctly
set PYTHONPATH=%~dp0;%~dp0packages\infrastructure;%~dp0packages\scrapers\google_maps\src

%PYTHON% start.py
pause
