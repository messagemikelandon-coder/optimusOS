@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Optimus 7.0.1 - Windows Setup
echo ============================================================
echo   LANDON MOTOR WORKS - OPTIMUS 7.0 WINDOWS SETUP
echo ============================================================
echo.

where powershell.exe >nul 2>nul
if errorlevel 1 (
    echo ERROR: Windows PowerShell was not found.
    echo Install or enable Windows PowerShell, then run this file again.
    pause
    exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows_setup.ps1"
set "SETUP_EXIT=%ERRORLEVEL%"

if not "%SETUP_EXIT%"=="0" (
    echo.
    echo Setup did not complete successfully.
    pause
    exit /b %SETUP_EXIT%
)

echo.
echo Setup completed.
echo Double-click local.bat to launch the Optimus Command Center.
pause
exit /b 0
