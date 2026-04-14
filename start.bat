@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"

echo Starting Calendar Assistant...
echo.

echo Cleaning up old processes...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 .*LISTENING"') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173 .*LISTENING"') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo Checking Ollama server...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing > $null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo Starting Ollama window...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:ComSpec -WorkingDirectory $env:ROOT -ArgumentList @('/k', 'call', ('\"' + $env:ROOT + 'start_ollama.bat\"'))"
    timeout /t 4 /nobreak >nul
) else (
    echo Ollama is already running.
)

echo Clearing Python cache...
for /d /r "%BACKEND%" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d" >nul 2>&1
)

echo Starting backend window...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:ComSpec -WorkingDirectory $env:ROOT -ArgumentList @('/k', 'call', ('\"' + $env:ROOT + 'start_backend.bat\"'))"

echo Waiting for backend to start...
timeout /t 4 /nobreak >nul

echo Starting frontend window...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:ComSpec -WorkingDirectory $env:FRONTEND -ArgumentList @('/k', 'call', ('\"' + $env:ROOT + 'start_frontend.bat\"'))"

echo Waiting for frontend to start...
timeout /t 4 /nobreak >nul

echo Opening app in browser...
start "" "http://localhost:5173"

echo.
echo Both servers were launched.
echo Ollama:   http://127.0.0.1:11434
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo.
echo If something fails, check the two opened terminal windows.
echo Close them to stop the servers.

pause
endlocal
