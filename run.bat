@echo off
cd /d "%~dp0"

set PORT=8001
set URL=http://localhost:%PORT%

if not exist logs mkdir logs

:: Check if already running
powershell -Command "try { Invoke-WebRequest -Uri '%URL%/api/health' -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 (
    start "" "%URL%"
    exit /b 0
)

:: Install deps if needed
python -m pip show fastapi >nul 2>&1
if %errorlevel% neq 0 (
    python -m pip install -r requirements.txt --quiet
)

:: Start server in a new minimized window, then open browser
start /min "Options Scanner Server" python server.py

:: Wait for it
:WAIT
timeout /t 2 /nobreak >nul
powershell -Command "try { Invoke-WebRequest -Uri '%URL%/api/health' -TimeoutSec 1 -UseBasicParsing -ErrorAction Stop | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% == 0 goto OPEN
set /a attempts+=1
if %attempts% lss 15 goto WAIT

echo Server did not start. Check that Python is installed.
pause
exit /b 1

:OPEN
start "" "%URL%"
exit /b 0
