@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "PYTHONPATH=%ROOT%"

echo Backend root: %ROOT%
echo Starting FastAPI server...
cd /d "%ROOT%"
"%BACKEND%\venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

echo.
echo Backend exited. Press any key to close this window.
pause >nul
endlocal
