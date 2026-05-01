@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "PYTHON=%BACKEND%\venv\Scripts\python.exe"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5174"
set "OLLAMA_BASE_URL=https://ollama.com"
set "OLLAMA_PORT=11434"
set "OLLAMA_MODEL=gpt-oss:20b-cloud"

if exist "%BACKEND%\.env" (
    for /f "usebackq tokens=1* delims==" %%a in (`findstr /b /c:"OLLAMA_BASE_URL=" "%BACKEND%\.env"`) do set "OLLAMA_BASE_URL=%%b"
    for /f "usebackq tokens=1* delims==" %%a in (`findstr /b /c:"OLLAMA_CHAT_MODEL=" "%BACKEND%\.env"`) do set "OLLAMA_MODEL=%%b"
)

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

:: ── Ensure Ollama is running and the recommended model exists ────────────────
echo [1/5] Checking Ollama...
call :ensure_ollama_ready "%OLLAMA_BASE_URL%"
if errorlevel 1 exit /b 1

:: ── Verify target ports are free ─────────────────────────────────────────────
echo [2/5] Checking ports %BACKEND_PORT% and %FRONTEND_PORT%...
call :ensure_port_free %BACKEND_PORT% Backend
if errorlevel 1 exit /b 1
call :ensure_port_free %FRONTEND_PORT% Frontend
if errorlevel 1 exit /b 1

:: ── Start backend in new window ──────────────────────────────────────────────
echo [3/5] Starting backend...
start "Calendar Backend" cmd /k "title Calendar Backend && cd /d "%ROOT%" && set PYTHONPATH=%ROOT% && "%PYTHON%" -m uvicorn backend.main:app --host 0.0.0.0 --port %BACKEND_PORT%"

:: ── Poll until /health responds (up to 120 s) ────────────────────────────────
echo [4/5] Waiting for backend (can take 20-30s on first run)...
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
echo [5/5] Starting frontend...
start "Calendar Frontend" cmd /k "title Calendar Frontend && cd /d "%FRONTEND%" && npm run dev -- --host 0.0.0.0 --port %FRONTEND_PORT% --strictPort"

:: ── Wait for Vite then open browser ──────────────────────────────────────────
timeout /t 5 /nobreak >nul
start "" "http://localhost:%FRONTEND_PORT%"

echo.
echo ================================================
echo  Ollama:    %OLLAMA_BASE_URL%  (%OLLAMA_MODEL%)
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

:ensure_ollama_ready
set "OLLAMA_BASE=%~1"
if /i not "%OLLAMA_BASE%"=="http://127.0.0.1:11434" if /i not "%OLLAMA_BASE%"=="http://localhost:11434" (
    echo   Using remote Ollama endpoint %OLLAMA_BASE%.
    exit /b 0
)

set "OLLAMA_PID="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort %OLLAMA_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess; if ($c) { $c }"`) do (
    set "OLLAMA_PID=%%p"
)

if not defined OLLAMA_PID (
    where ollama >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Ollama was not found in PATH.
        echo Install Ollama from https://ollama.com/download and rerun start.bat
        pause
        exit /b 1
    )

    echo   Starting Ollama server in a new window...
    start "Calendar Ollama" cmd /k "title Calendar Ollama && ollama serve"
)

set /a ollama_elapsed=0
:wait_ollama_loop
curl -s -f -o nul --max-time 2 http://127.0.0.1:%OLLAMA_PORT%/api/tags >nul 2>&1
if !errorlevel!==0 goto ollama_ready
if !ollama_elapsed! geq 60 goto ollama_timeout
timeout /t 2 /nobreak >nul
set /a ollama_elapsed+=2
goto wait_ollama_loop

:ollama_timeout
echo ERROR: Ollama did not start within 60s.
echo Check the "Calendar Ollama" window for errors.
pause
exit /b 1

:ollama_ready
where ollama >nul 2>&1
if errorlevel 1 (
    echo   Ollama server is running, but the CLI is not available to verify the model.
    exit /b 0
)

ollama list | findstr /i /c:"%OLLAMA_MODEL%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Ollama model %OLLAMA_MODEL% is not available in your current Ollama account.
    echo Open the Ollama app, sign in to Ollama Cloud, and make sure this model is available.
    echo You can also change OLLAMA_CHAT_MODEL in backend\.env if you prefer another cloud model.
    pause
    exit /b 1
)
exit /b 0

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
