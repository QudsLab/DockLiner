#!/usr/bin/env pwsh
# DockLiner uninstaller for Windows / PowerShell

$INSTALL_DIR = if ($env:DOCKLINER_INSTALL_DIR) { $env:DOCKLINER_INSTALL_DIR } else { "C:\ProgramData\DockLiner" }
$SERVICE_NAME = "dockliner"

Write-Host "==> DockLiner uninstall" -ForegroundColor Cyan
Write-Host "Install dir: $INSTALL_DIR"

# 1. Stop/remove Windows service if it exists
$svc = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($svc) {
    Write-Host "==> Stopping Windows service: $SERVICE_NAME" -ForegroundColor Cyan
    Stop-Service $SERVICE_NAME -ErrorAction SilentlyContinue
    sc.exe delete $SERVICE_NAME | Out-Null
}

# 2. Keep live DB if requested / if non-sqlite
if (Test-Path "$INSTALL_DIR\.env") {
    $line = Get-Content "$INSTALL_DIR\.env" | Select-String '^DOCKLINER_DB_TYPE=' | Select-Object -First 1
    $dbType = if ($line) { ($line -split '=')[1] } else { "sqlite" }
    if ($dbType -ne "sqlite" -and (Test-Path "$INSTALL_DIR\db")) {
        Write-Host "==> Live DB detected in $INSTALL_DIR\db — keeping it (remove manually if you want it gone)." -ForegroundColor Yellow
    }
}

# 3. Remove install directory
if (Test-Path $INSTALL_DIR) {
    Write-Host "==> Removing $INSTALL_DIR" -ForegroundColor Cyan
    Remove-Item -Recurse -Force -Path $INSTALL_DIR -ErrorAction SilentlyContinue
}

# 4. Delete this uninstall script
$scriptPath = $MyInvocation.MyCommand.Path
if ($scriptPath -and (Test-Path $scriptPath)) {
    Write-Host "==> Removing uninstall script" -ForegroundColor Cyan
    Remove-Item -Path $scriptPath -Force -ErrorAction SilentlyContinue
}

Write-Host "==> DockLiner removed." -ForegroundColor Green
