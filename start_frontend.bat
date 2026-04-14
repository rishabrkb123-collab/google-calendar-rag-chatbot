@echo off
setlocal

set "ROOT=%~dp0"
set "FRONTEND=%ROOT%frontend"

echo Frontend root: %FRONTEND%
echo Starting Vite dev server...
cd /d "%FRONTEND%"
npm run dev

echo.
echo Frontend exited. Press any key to close this window.
pause >nul
endlocal
