@echo off
REM DockLiner uninstaller for Windows Command Prompt

set "INSTALL_DIR=%DOCKLINER_INSTALL_DIR%"
if "%INSTALL_DIR%"=="" set "INSTALL_DIR=%ProgramData%\DockLiner"
set "SERVICE_NAME=dockliner"

echo ==^> DockLiner uninstall
echo Install dir: %INSTALL_DIR%

REM 1. Stop/remove Windows service if it exists
sc query %SERVICE_NAME% >NUL 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ==^> Stopping Windows service: %SERVICE_NAME%
    net stop %SERVICE_NAME% >NUL 2>&1
    sc delete %SERVICE_NAME% >NUL 2>&1
)

REM 2. Keep live DB if non-sqlite
if exist "%INSTALL_DIR%\.env" (
    for /f "tokens=2 delims==" %%a in ('findstr /B "DOCKLINER_DB_TYPE=" "%INSTALL_DIR%\.env"') do set "DB_TYPE=%%a"
    if "%DB_TYPE%"=="" set "DB_TYPE=sqlite"
    if not "%DB_TYPE%"=="sqlite" (
        if exist "%INSTALL_DIR%\db" (
            echo ==^> Live DB detected in %INSTALL_DIR%\db — keeping it.
        )
    )
)

REM 3. Remove install directory
if exist "%INSTALL_DIR%" (
    echo ==^> Removing %INSTALL_DIR%
    rmdir /s /q "%INSTALL_DIR%"
)

REM 4. Delete this uninstall script
if exist "%~f0" (
    echo ==^> Removing uninstall script
    del "%~f0"
)

echo ==^> DockLiner removed.
