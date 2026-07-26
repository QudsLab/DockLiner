#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/QudsLab/DockLiner.git"
INSTALL_DIR="/opt/dockliner"
SERVICE_NAME="dockliner"

# Allow override from environment
INSTALL_DIR="${DOCKLINER_INSTALL_DIR:-$INSTALL_DIR}"

# --- terminal-aware colors ---------------------------------------------------
if [ -t 1 ] || [ "${CLICOLOR_FORCE:-0}" = "1" ]; then
  BOLD=$(printf '%b' '\e[1m')
  GREEN=$(printf '%b' '\e[0;32m')
  YELLOW=$(printf '%b' '\e[0;33m')
  RED=$(printf '%b' '\e[0;31m')
  CYAN=$(printf '%b' '\e[0;36m')
  DIM=$(printf '%b' '\e[0;90m')
  RESET=$(printf '%b' '\e[0m')
  CHECK='✓'
  CROSS='✗'
  INFO='•'
else
  BOLD='' GREEN='' YELLOW='' RED='' CYAN='' DIM='' RESET=''
  CHECK='[OK]' CROSS='[ERR]' INFO='[i]'
fi

# --- helpers -----------------------------------------------------------------
log()     { printf "%b%s%b\n" "$DIM" "$1" "$RESET"; }
info()    { printf "%b%s%b %s\n" "$CYAN" "$INFO" "$RESET" "$1"; }
ok()      { printf "%b%s%b %s\n" "$GREEN" "$CHECK" "$RESET" "$1"; }
warn()    { printf "%b%s%b %s\n" "$YELLOW" "!" "$RESET" "$1"; }
fail()    { printf "%b%s%b %s\n" "$RED" "$CROSS" "$RESET" "$1" >&2; }
header()  { printf "\n%b==>%b %s\n" "$BOLD" "$RESET" "$1"; }

# Print a line and run a command; show status on failure
run() {
  local msg="$1"
  shift
  info "$msg"
  if "$@"; then
    ok "$msg"
  else
    fail "$msg"
    return 1
  fi
}

# Run apt-get non-interactively if present
apt_install() {
  local pkgs="$*"
  DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $pkgs >/dev/null
}

# Try to install missing packages; prints instructions and exits if impossible
try_install() {
  local bin="$1"
  local pkg="$2"

  if command -v "$bin" &>/dev/null; then
    return 0
  fi

  warn "$bin not found"

  if [ "$(id -u)" -ne 0 ]; then
    fail "Need root to install system packages. Run as root, or install $pkg manually."
    exit 1
  fi

  if command -v apt-get &>/dev/null; then
    run "Installing $pkg via apt" apt_install "$pkg"
  elif command -v dnf &>/dev/null; then
    run "Installing $pkg via dnf" dnf install -y "$pkg"
  elif command -v yum &>/dev/null; then
    run "Installing $pkg via yum" yum install -y "$pkg"
  else
    fail "No supported package manager found. Please install $pkg manually."
    exit 1
  fi
}

# ------------------------------------------------------------------------------
header "DockLiner one-run setup"
info "Install dir: $INSTALL_DIR"

# --- 1. Ensure dependencies ----------------------------------------------------
header "Checking dependencies"

try_install git git
try_install python3 python3
ok "git is installed"
ok "python3 is ready"

# --- 2. Clone or update -------------------------------------------------------
if [ -d "$INSTALL_DIR/.git" ]; then
  header "Updating existing repo at $INSTALL_DIR"
  cd "$INSTALL_DIR"
  run "Pulling latest changes" git pull origin main
else
  header "Cloning $REPO into $INSTALL_DIR"
  run "Cloning repository" git clone "$REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# --- 3. Ensure python3-pip is available -------------------------------------
if ! python3 -m pip --version &>/dev/null; then
  warn "python3-pip is missing"
  if [ "$(id -u)" -ne 0 ]; then
    fail "Need root to install python3-pip. Run as root or install it manually."
    exit 1
  fi
  if command -v apt-get &>/dev/null; then
    run "Installing python3-pip via apt" apt_install python3-pip
  elif command -v dnf &>/dev/null; then
    run "Installing python3-pip via dnf" dnf install -y python3-pip
  elif command -v yum &>/dev/null; then
    run "Installing python3-pip via yum" yum install -y python3-pip
  else
    fail "python3-pip missing and no supported package manager found."
    exit 1
  fi
fi
ok "python3-pip is ready"

# --- 4. Install / upgrade Python dependencies ---------------------------------
header "Installing Python dependencies"
run "Upgrading pip" python3 -m pip install --upgrade pip
run "Installing requirements" python3 -m pip install -r "$INSTALL_DIR/requirements.txt"

# --- 5. Ensure .env exists (env-driven config) -------------------------------
if [ ! -f "$INSTALL_DIR/.env" ]; then
  header "Creating default .env"
  run "Generating default environment" python3 -c \
    "from app.env_maker import refine_env; print(refine_env(''))" \> "$INSTALL_DIR/.env"
else
  ok "Environment file exists"
fi

# --- 6. Ensure required directories exist -------------------------------------
header "Preparing directories"
run "Creating projects/downloads/logs directories" \
  mkdir -p "$INSTALL_DIR/projects" "$INSTALL_DIR/downloads" "$INSTALL_DIR/logs"

# --- 7. Create systemd service if systemd is available ------------------------
if command -v systemctl &>/dev/null; then
  header "Installing systemd service: $SERVICE_NAME"
  cat > "/tmp/$SERVICE_NAME.service" <<EOF
[Unit]
Description=DockLiner deployment manager
After=network.target

[Service]
Type=simple
User=root
Group=docker
WorkingDirectory=$INSTALL_DIR
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="DOCKLINER_SERVICE=$SERVICE_NAME"
Environment="DOCKLINER_ENV_FILE=$INSTALL_DIR/.env"
ExecStart=python3 $INSTALL_DIR/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  run "Installing service file" mv "/tmp/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
  run "Reloading systemd" systemctl daemon-reload
  run "Enabling $SERVICE_NAME" systemctl enable "$SERVICE_NAME"
  info "Starting service"
  systemctl restart "$SERVICE_NAME" || warn "Service start failed; check 'systemctl status $SERVICE_NAME'"
else
  warn "systemd not detected; skipping service installation"
  info "To start manually: python3 $INSTALL_DIR/main.py"
fi

# --- 8. Done ------------------------------------------------------------------
printf "\n%b===============================================%b\n" "$BOLD" "$RESET"
ok "DockLiner setup complete"
info "Install dir : $INSTALL_DIR"
info "Config file : $INSTALL_DIR/.env"
info "Service     : $SERVICE_NAME"
if command -v systemctl &>/dev/null; then
  info "Status      : systemctl status $SERVICE_NAME"
  info "Logs        : journalctl -u $SERVICE_NAME -f"
fi
WEB_PORT=$(grep -E '^DOCKLINER_PORT=' "$INSTALL_DIR/.env" | cut -d'=' -f2 || echo "50021")
info "Web UI      : http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
info "Default user: root / qwer.1234"
printf "%b===============================================%b\n" "$BOLD" "$RESET"
warn "Change the default password in Settings → Config after first login."
