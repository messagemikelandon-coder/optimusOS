@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Optimus is not installed. Run WINDOWS_SETUP.bat first.
    pause
    exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\reset_openai_key.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
    echo The new OpenAI key passed all checks.
) else (
    echo The key or API account still failed. Read the specific RESULT line above.
)
pause
exit /b %RESULT%
