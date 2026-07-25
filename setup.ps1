#!/usr/bin/env pwsh
# DockLiner one-run setup for Windows / PowerShell

$REPO = "https://github.com/QudsLab/DockLiner.git"
$INSTALL_DIR = if ($env:DOCKLINER_INSTALL_DIR) { $env:DOCKLINER_INSTALL_DIR } else { "C:\ProgramData\DockLiner" }
$SERVICE_NAME = "dockliner"

Write-Host "==> DockLiner one-run setup" -ForegroundColor Cyan
Write-Host "Install dir: $INSTALL_DIR"

# 1. Ensure dependencies
Write-Host "==> Checking dependencies" -ForegroundColor Cyan
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git is required. Install Git for Windows first."
    exit 1
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python is required. Install Python 3.11+ for Windows first."
    exit 1
}

# 2. Clone or update
if (Test-Path "$INSTALL_DIR\.git") {
    Write-Host "==> Updating existing repo at $INSTALL_DIR" -ForegroundColor Cyan
    Set-Location $INSTALL_DIR
    git pull origin main
} else {
    Write-Host "==> Cloning $REPO into $INSTALL_DIR" -ForegroundColor Cyan
    git clone $REPO $INSTALL_DIR
    Set-Location $INSTALL_DIR
}

# 3. Create Python virtual environment
if (-not (Test-Path "$INSTALL_DIR\venv")) {
    Write-Host "==> Creating Python virtual environment" -ForegroundColor Cyan
    python -m venv "$INSTALL_DIR\venv"
}

# 4. Install / upgrade Python dependencies
Write-Host "==> Installing Python dependencies" -ForegroundColor Cyan
& "$INSTALL_DIR\venv\Scripts\python.exe" -m pip install --upgrade pip
& "$INSTALL_DIR\venv\Scripts\pip.exe" install -r "$INSTALL_DIR\requirements.txt"

# 5. Ensure .env exists
if (-not (Test-Path "$INSTALL_DIR\.env")) {
    Write-Host "==> Creating default .env" -ForegroundColor Cyan
    $envContent = & "$INSTALL_DIR\venv\Scripts\python.exe" -c "from app.env_maker import refine_env; print(refine_env(''))"
    Set-Content -Path "$INSTALL_DIR\.env" -Value $envContent -Encoding UTF8
}

# 6. Ensure required directories exist
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\projects" | Out-Null
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\downloads" | Out-Null
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\logs" | Out-Null

# 7. Try to create a Windows service via nssm (optional)
$Nssm = Get-Command nssm -ErrorAction SilentlyContinue
if ($Nssm) {
    Write-Host "==> Installing Windows service: $SERVICE_NAME" -ForegroundColor Cyan
    & nssm install $SERVICE_NAME "$INSTALL_DIR\venv\Scripts\python.exe" "$INSTALL_DIR\main.py"
    nssm set $SERVICE_NAME AppDirectory $INSTALL_DIR
    nssm set $SERVICE_NAME AppEnvironmentExtra "DOCKLINER_SERVICE=$SERVICE_NAME"
    Start-Service $SERVICE_NAME -ErrorAction SilentlyContinue
} else {
    Write-Host "==> nssm not found; skipping Windows service installation" -ForegroundColor Yellow
    Write-Host "    To start manually: $INSTALL_DIR\venv\Scripts\python.exe $INSTALL_DIR\main.py"
}

# 8. Done
$WebPort = (Get-Content "$INSTALL_DIR\.env" | Select-String '^DOCKLINER_PORT=') -replace 'DOCKLINER_PORT=', ''
if (-not $WebPort) { $WebPort = "50021" }
$HostIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' } | Select-Object -First 1).IPAddress
if (-not $HostIp) { $HostIp = "127.0.0.1" }

Write-Host ""
Write-Host "===============================================" -ForegroundColor Green
Write-Host "DockLiner setup complete." -ForegroundColor Green
Write-Host "Install dir : $INSTALL_DIR"
Write-Host "Config file : $INSTALL_DIR\.env"
Write-Host "Service     : $SERVICE_NAME"
Write-Host "Web UI      : http://${HostIp}:$WebPort"
Write-Host "Default user: root / qwer.1234"
Write-Host "===============================================" -ForegroundColor Green
Write-Host "Change the default password in Settings → Config after first login."
