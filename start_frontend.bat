@echo off
setlocal

set "ROOT=%~dp0"
set "FRONTEND=%ROOT%frontend"

echo Frontend root: %FRONTEND%
echo Starting Vite dev server on port 5174...
cd /d "%FRONTEND%"
npm run dev -- --host 0.0.0.0 --port 5174 --strictPort

echo.
echo Frontend exited. Press any key to close this window.
pause >nul
endlocal
