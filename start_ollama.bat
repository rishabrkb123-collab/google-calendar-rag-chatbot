@echo off
setlocal

where ollama >nul 2>&1
if errorlevel 1 (
    echo Ollama CLI was not found.
    echo Install Ollama from https://ollama.com/download.
    echo.
    echo Press any key to close this window.
    pause >nul
    exit /b 1
)

echo This project is configured to use Ollama Cloud by default.
echo start_ollama.bat is only needed if you switch OLLAMA_BASE_URL back to a local server.
echo.
echo Starting a local Ollama server anyway...

ollama serve

echo.
echo Ollama exited. Press any key to close this window.
pause >nul
endlocal
