@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Optimus 7.0.1 - Estimator Diagnostic

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Optimus is not installed in this folder.
    echo Run WINDOWS_SETUP.bat first.
    pause
    exit /b 1
)

if not exist ".env" (
    echo ERROR: .env is missing.
    echo Run WINDOWS_SETUP.bat first.
    pause
    exit /b 1
)

echo This test performs one live web-research estimate and may use API credits.
echo.
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\diagnose_estimator.py"
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
    echo Estimator diagnostic passed.
) else (
    echo Estimator diagnostic failed with code %RESULT%.
)
pause
exit /b %RESULT%
