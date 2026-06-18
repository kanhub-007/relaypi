@echo off
REM start.bat — launch relaypi (telegramy must already be running)

cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo.
echo ========================================
echo   RelayPI
echo ========================================
echo.

echo Checking dependencies...
python -m relaypi.preflight
if %ERRORLEVEL% NEQ 0 (
    echo.
    pause
    exit /b 1
)

echo.
echo Starting relaypi (Ctrl+C to stop)...
echo.

python -m relaypi.main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo relaypi exited with code %ERRORLEVEL%
    pause
)
