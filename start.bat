@echo off
REM start.bat — launch relaypi (telegramy must already be running)

cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo Starting relaypi...
echo.

python -m relaypi.main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo relaypi exited with code %ERRORLEVEL%
    pause
)
