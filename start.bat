@echo off
setlocal

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%frontend

echo Starting Calendar Assistant...
echo.

REM Start backend in a new persistent terminal window
start "Calendar Backend" cmd /k "cd /d "%ROOT%" && backend\venv\Scripts\activate && uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"

REM Wait for backend to be ready
echo Waiting for backend to start...
timeout /t 4 /nobreak >nul

REM Start frontend in a new persistent terminal window
start "Calendar Frontend" cmd /k "cd /d "%FRONTEND%" && npm run dev"

REM Wait for frontend to be ready
echo Waiting for frontend to start...
timeout /t 5 /nobreak >nul

REM Open browser
echo Opening browser...
start http://localhost:5173

echo.
echo Both servers are running.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo.
echo Close the two terminal windows to stop the servers.
endlocal
