@echo off
setlocal

where ollama >nul 2>&1
if errorlevel 1 (
    echo Ollama CLI was not found.
    echo Install Ollama from https://ollama.com/download and pull the required models.
    echo Required models:
    echo   ollama pull llama3.1:8b
    echo   ollama pull nomic-embed-text:latest
    echo.
    echo Press any key to close this window.
    pause >nul
    exit /b 1
)

echo Starting Ollama server...
ollama serve

echo.
echo Ollama exited. Press any key to close this window.
pause >nul
endlocal
