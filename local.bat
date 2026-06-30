@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Optimus 7.0.1 - Landon Motor Works

if not exist ".venv\Scripts\python.exe" (
    echo Optimus is not installed yet. Starting Windows setup...
    call "%~dp0WINDOWS_SETUP.bat"
    if errorlevel 1 exit /b 1
)

if not exist ".env" (
    echo ERROR: .env is missing.
    echo Run WINDOWS_SETUP.bat first.
    pause
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\validate_runtime.py"
if errorlevel 1 (
    echo.
    echo Fix the configuration shown above, or run WINDOWS_SETUP.bat again.
    pause
    exit /b 1
)

set "OPTIMUS_TOKEN="
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"OPTIMUS_ACCESS_TOKEN=" ".env"`) do set "OPTIMUS_TOKEN=%%B"
if defined OPTIMUS_TOKEN (
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Set-Clipboard -Value $env:OPTIMUS_TOKEN" >nul 2>nul
)

echo.
echo ============================================================
echo   LANDON MOTOR WORKS - OPTIMUS 7.0.1 COMMAND CENTER
echo ============================================================
echo   Local address: http://127.0.0.1:8000
echo   Access token: loaded automatically into the browser tab
echo   Server scope: this computer only
echo.
echo   Press Ctrl+C in this window to stop Optimus.
echo ============================================================
echo.

start "" powershell.exe -NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0scripts\open_when_ready.ps1" -Url "http://127.0.0.1:8000" -HealthUrl "http://127.0.0.1:8000/health" -AccessToken "%OPTIMUS_TOKEN%"

"%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
set "SERVER_EXIT=%ERRORLEVEL%"

if not "%SERVER_EXIT%"=="0" (
    echo.
    echo Optimus stopped with error code %SERVER_EXIT%.
    echo If port 8000 is already in use, close the other Optimus window.
    pause
)

exit /b %SERVER_EXIT%
