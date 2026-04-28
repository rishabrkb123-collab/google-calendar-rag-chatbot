@echo off
setlocal

where ollama >nul 2>&1
if errorlevel 1 (
    echo Ollama CLI was not found.
    echo Install Ollama from https://ollama.com/download.
    echo This project uses an Ollama cloud chat model configured in backend\.env
    echo and local Sentence Transformers embeddings loaded by the Python backend.
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
