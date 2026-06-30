@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Optimus is not installed. Run WINDOWS_SETUP.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\validate_runtime.py
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
echo Checking which OpenAI key Optimus is actually using...
".venv\Scripts\python.exe" scripts\diagnose_openai_config.py
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
echo Checking OpenAI API connection...
".venv\Scripts\python.exe" scripts\check_openai.py
if errorlevel 1 (
    echo.
    echo OpenAI connection test failed.
    echo Run RESET_OPENAI_KEY.bat to replace and retest the project key.
    pause
    exit /b 1
)

echo.
echo Running automated tests...
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 (
    echo.
    echo Automated tests failed.
    pause
    exit /b 1
)

echo.
echo All checks passed.
pause
exit /b 0
