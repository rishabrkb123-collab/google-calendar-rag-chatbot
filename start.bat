@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "PYTHON=%BACKEND%\venv\Scripts\python.exe"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5174"

echo ================================================
echo  Calendar Assistant - Starting up
echo ================================================
echo.

:: ── Verify Python venv exists ───────────────────────────────────────────────
if not exist "%PYTHON%" (
    echo ERROR: Python venv not found at:
    echo   %PYTHON%
    echo.
    echo Run:  cd backend ^&^& python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: ── Verify target ports are free ─────────────────────────────────────────────
echo [1/4] Checking ports %BACKEND_PORT% and %FRONTEND_PORT%...
call :ensure_port_free %BACKEND_PORT% Backend
if errorlevel 1 exit /b 1
call :ensure_port_free %FRONTEND_PORT% Frontend
if errorlevel 1 exit /b 1

:: ── Start backend in new window ──────────────────────────────────────────────
echo [2/4] Starting backend...
start "Calendar Backend" cmd /k "title Calendar Backend && cd /d "%ROOT%" && set PYTHONPATH=%ROOT% && "%PYTHON%" -m uvicorn backend.main:app --host 0.0.0.0 --port %BACKEND_PORT%"

:: ── Poll until /health responds (up to 120 s) ────────────────────────────────
echo [3/4] Waiting for backend (can take 20-30s on first run)...
set /a elapsed=0

:wait_loop
timeout /t 2 /nobreak >nul
set /a elapsed+=2
curl -s -f -o nul --max-time 2 http://localhost:%BACKEND_PORT%/health >nul 2>&1
if !errorlevel!==0 goto backend_ready
if !elapsed! geq 120 goto backend_timeout
set /a mod5=!elapsed! %% 10
if !mod5!==0 echo   ...!elapsed!s
goto wait_loop

:backend_timeout
echo.
echo ERROR: Backend did not start within 120s.
echo Check the "Calendar Backend" window for the Python error.
echo.
pause
exit /b 1

:backend_ready
echo   Backend ready after !elapsed!s!

:: ── Start frontend in new window ─────────────────────────────────────────────
echo [4/4] Starting frontend...
start "Calendar Frontend" cmd /k "title Calendar Frontend && cd /d "%FRONTEND%" && npm run dev -- --host 0.0.0.0 --port %FRONTEND_PORT% --strictPort"

:: ── Wait for Vite then open browser ──────────────────────────────────────────
timeout /t 5 /nobreak >nul
start "" "http://localhost:%FRONTEND_PORT%"

echo.
echo ================================================
echo  Backend:   http://localhost:%BACKEND_PORT%
echo  Frontend:  http://localhost:%FRONTEND_PORT%
echo ================================================
echo.
echo Both services are running in their own windows.
echo Close the "Calendar Backend" and "Calendar Frontend" windows to stop.
echo.
pause
endlocal
goto :eof

:ensure_port_free
set "TARGET_PORT=%~1"
set "SERVICE_NAME=%~2"
set "FOUND_PID="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort %TARGET_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess; if ($c) { $c }"`) do (
    set "FOUND_PID=%%p"
)
if defined FOUND_PID (
    echo ERROR: %SERVICE_NAME% port %TARGET_PORT% is already in use by PID !FOUND_PID!.
    powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=!FOUND_PID!'; if ($p) { $p | Select-Object ProcessId, Name, CommandLine | Format-List }"
    echo.
    echo Close that process or choose a different port for this project.
    pause
    exit /b 1
)
exit /b 0
