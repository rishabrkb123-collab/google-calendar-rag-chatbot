@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%"
cd /d "%ROOT%"
echo Backend root: %ROOT%
echo Starting FastAPI on port 8000...
echo.
"%ROOT%backend\venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
echo.
echo Backend stopped. Press any key to close.
pause >nul
endlocal
