@echo off
REM DockLiner minimal one-run setup for Windows Command Prompt

set "INSTALL_DIR=%DOCKLINER_INSTALL_DIR%"
if "%INSTALL_DIR%"=="" set "INSTALL_DIR=%ProgramData%\DockLiner"
set "SERVICE_NAME=dockliner"

echo ==^> DockLiner one-run setup
echo Install dir: %INSTALL_DIR%

REM 1. Check dependencies
git --version >NUL 2>&1
if errorlevel 1 (
    echo git is required. Install Git for Windows first.
    exit /b 1
)
python --version >NUL 2>&1
if errorlevel 1 (
    echo python is required. Install Python 3.11+ for Windows first.
    exit /b 1
)

REM 2. Clone or update
if exist "%INSTALL_DIR%\.git" (
    echo ==^> Updating existing repo at %INSTALL_DIR%
    cd /d "%INSTALL_DIR%"
    git pull origin main
) else (
    echo ==^> Cloning https://github.com/QudsLab/DockLiner.git into %INSTALL_DIR%
    git clone "https://github.com/QudsLab/DockLiner.git" "%INSTALL_DIR%"
    cd /d "%INSTALL_DIR%"
)

REM 3. Install dependencies
echo ==^> Installing Python dependencies
python -m pip install --upgrade pip
python -m pip install -r "%INSTALL_DIR%\requirements.txt"

REM 4. Ensure .env exists
if not exist "%INSTALL_DIR%\.env" (
    echo ==^> Creating default .env
    python -c "from app.env_maker import refine_env; print(refine_env(''))" > "%INSTALL_DIR%\.env"
)

REM 5. Ensure dirs exist
mkdir "%INSTALL_DIR%\projects" 2>NUL
mkdir "%INSTALL_DIR%\downloads" 2>NUL
mkdir "%INSTALL_DIR%\logs" 2>NUL

REM 6. Start hint
for /f "tokens=2 delims==" %%a in ('findstr /B "DOCKLINER_PORT=" "%INSTALL_DIR%\.env"') do set "WEB_PORT=%%a"
if "%WEB_PORT%"=="" set "WEB_PORT=50021"

echo.
echo ===============================================
echo DockLiner setup complete.
echo Install dir : %INSTALL_DIR%
echo Config file : %INSTALL_DIR%\.env
echo Service     : %SERVICE_NAME%
echo Web UI      : http://127.0.0.1:%WEB_PORT%
echo Default user: root / qwer.1234
echo ===============================================
echo To start manually: python "%INSTALL_DIR%\main.py"
