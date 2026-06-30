@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Optimus is not installed. Run WINDOWS_SETUP.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\diagnose_openai_config.py
echo.
".venv\Scripts\python.exe" scripts\check_openai.py
set "RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %RESULT%
