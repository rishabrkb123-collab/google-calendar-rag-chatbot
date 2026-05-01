@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "VENV_DIR=%BACKEND%\venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"
set "LOG_DIR=%ROOT%install_logs"
set "BACKEND_LOG=%LOG_DIR%\backend_install.log"
set "FRONTEND_LOG=%LOG_DIR%\frontend_install.log"
set "VERIFY_LOG=%LOG_DIR%\verification.log"
set "PYTHON_CMD="
set "NPM_CMD="
set "BACKEND_STATUS=NOT RUN"
set "FRONTEND_STATUS=NOT RUN"
set "VERIFY_STATUS=NOT RUN"

echo ================================================
echo  Calendar Assistant - Dependency Installer
echo ================================================
echo.

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
del /q "%BACKEND_LOG%" "%FRONTEND_LOG%" "%VERIFY_LOG%" >nul 2>&1

if not exist "%BACKEND%\requirements.txt" (
    echo ERROR: Missing backend\requirements.txt
    goto :fail
)

if not exist "%FRONTEND%\package.json" (
    echo ERROR: Missing frontend\package.json
    goto :fail
)

where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    ) else (
        echo ERROR: Python was not found in PATH.
        echo Install Python 3.11+ and enable "Add python.exe to PATH".
        goto :fail
    )
)

where npm >nul 2>&1
if not errorlevel 1 (
    set "NPM_CMD=npm"
) else (
    echo ERROR: npm was not found in PATH.
    echo Install Node.js 20+ so npm is available.
    goto :fail
)

echo [1/6] Using Python command:
echo   %PYTHON_CMD%
echo [2/6] Using npm command:
echo   %NPM_CMD%
echo Logs will be written to:
echo   %LOG_DIR%
echo.

if not exist "%VENV_PYTHON%" (
    echo [3/6] Creating backend virtual environment...
    call %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo ERROR: Failed to create backend virtual environment.
        goto :fail
    )
) else (
    echo [3/6] Backend virtual environment already exists.
)

echo [4/6] Upgrading pip tooling with a torch-compatible setuptools version...
call "%VENV_PYTHON%" -m pip install --upgrade pip "setuptools<82" wheel >> "%BACKEND_LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip tooling.
    set "BACKEND_STATUS=FAILED"
    goto :fail
)

echo [5/6] Installing backend Python packages...
call "%VENV_PIP%" install -r "%BACKEND%\requirements.txt" >> "%BACKEND_LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: Failed to install backend dependencies.
    set "BACKEND_STATUS=FAILED"
    goto :fail
)
set "BACKEND_STATUS=OK"

echo [6/6] Installing frontend Node packages...
if exist "%FRONTEND%\package-lock.json" (
    pushd "%FRONTEND%" >nul
    call %NPM_CMD% ci >> "%FRONTEND_LOG%" 2>&1
    set "NPM_EXIT=!errorlevel!"
    popd >nul
) else (
    pushd "%FRONTEND%" >nul
    call %NPM_CMD% install >> "%FRONTEND_LOG%" 2>&1
    set "NPM_EXIT=!errorlevel!"
    popd >nul
)

if not "%NPM_EXIT%"=="0" (
    echo ERROR: Failed to install frontend dependencies.
    set "FRONTEND_STATUS=FAILED"
    goto :fail
)
set "FRONTEND_STATUS=OK"

echo.
echo Running quick verification checks...
call "%VENV_PYTHON%" -c "import backend.main" >> "%VERIFY_LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: Backend import verification failed.
    echo Check backend\.env, Python dependencies, or local model-related setup.
    set "VERIFY_STATUS=FAILED"
    goto :fail
)

pushd "%FRONTEND%" >nul
call %NPM_CMD% run build >> "%VERIFY_LOG%" 2>&1
set "FRONTEND_BUILD_EXIT=!errorlevel!"
popd >nul

if not "%FRONTEND_BUILD_EXIT%"=="0" (
    echo ERROR: Frontend build verification failed.
    set "VERIFY_STATUS=FAILED"
    goto :fail
)
set "VERIFY_STATUS=OK"

echo.
echo ================================================
echo  Dependency installation completed successfully.
echo ================================================
echo.
echo Summary:
echo   Backend packages:   %BACKEND_STATUS%
echo   Frontend packages:  %FRONTEND_STATUS%
echo   Verification:       %VERIFY_STATUS%
echo.
echo Installed and verified:
echo   - backend virtual environment at %VENV_DIR%
echo   - backend Python packages from backend\requirements.txt
echo   - frontend Node packages from frontend\package.json
echo   - backend import check
echo   - frontend production build check
echo.
echo Logs:
echo   - %BACKEND_LOG%
echo   - %FRONTEND_LOG%
echo   - %VERIFY_LOG%
echo.
echo Next steps:
echo   - Install Ollama from https://ollama.com/download if not already installed
echo   - Sign in to Ollama Cloud and make sure gpt-oss:20b-cloud is available in your Ollama app/account
echo   - Start local app with start.bat
echo   - Configure backend\.env and Google OAuth credentials if not done yet
echo.
pause
exit /b 0

:fail
echo.
echo Summary:
echo   Backend packages:   %BACKEND_STATUS%
echo   Frontend packages:  %FRONTEND_STATUS%
echo   Verification:       %VERIFY_STATUS%
echo.
echo Review logs for details:
echo   - %BACKEND_LOG%
echo   - %FRONTEND_LOG%
echo   - %VERIFY_LOG%
echo.
if exist "%BACKEND_LOG%" (
    echo Recent backend log lines:
    powershell -NoProfile -Command "Get-Content -Path '%BACKEND_LOG%' -Tail 20" 2>nul
    echo.
)
if exist "%FRONTEND_LOG%" (
    echo Recent frontend log lines:
    powershell -NoProfile -Command "Get-Content -Path '%FRONTEND_LOG%' -Tail 20" 2>nul
    echo.
)
if exist "%VERIFY_LOG%" (
    echo Recent verification log lines:
    powershell -NoProfile -Command "Get-Content -Path '%VERIFY_LOG%' -Tail 20" 2>nul
    echo.
)
echo Installation did not complete.
pause
exit /b 1
