#!/usr/bin/env bash
set -e

REPO="https://github.com/QudsLab/DockLiner.git"
INSTALL_DIR="/opt/dockliner"
SERVICE_NAME="dockliner"

# Allow override from environment
if [ -n "$DOCKLINER_INSTALL_DIR" ]; then
  INSTALL_DIR="$DOCKLINER_INSTALL_DIR"
fi

echo "==> DockLiner one-run setup"
echo "Install dir: $INSTALL_DIR"

# 1. Ensure dependencies
echo "==> Checking dependencies"
if ! command -v git &>/dev/null; then
  echo "git is required. Install it first (e.g. apt install git / yum install git)."
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  echo "python3 is required. Install it first (e.g. apt install python3 python3-venv python3-pip)."
  exit 1
fi

# 2. Clone or update
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> Updating existing repo at $INSTALL_DIR"
  cd "$INSTALL_DIR"
  git pull origin main
else
  echo "==> Cloning $REPO into $INSTALL_DIR"
  git clone "$REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# 3. Create Python virtual environment
if [ ! -d "$INSTALL_DIR/venv" ]; then
  echo "==> Creating Python virtual environment"
  python3 -m venv "$INSTALL_DIR/venv"
fi

# 4. Install / upgrade Python dependencies
echo "==> Installing Python dependencies"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# 5. Ensure .env exists (env-driven config)
if [ ! -f "$INSTALL_DIR/.env" ]; then
  echo "==> Creating default .env"
  "$INSTALL_DIR/venv/bin/python" -c "from app.env_maker import refine_env; print(refine_env(''))" > "$INSTALL_DIR/.env"
fi

# 6. Ensure required directories exist
mkdir -p "$INSTALL_DIR/projects" "$INSTALL_DIR/downloads" "$INSTALL_DIR/logs"

# 7. Create systemd service if systemd is available
if command -v systemctl &>/dev/null; then
  echo "==> Installing systemd service: $SERVICE_NAME"
  cat > "/tmp/$SERVICE_NAME.service" <<EOF
[Unit]
Description=DockLiner deployment manager
After=network.target

[Service]
Type=simple
User=root
Group=docker
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="DOCKLINER_SERVICE=$SERVICE_NAME"
Environment="DOCKLINER_ENV_FILE=$INSTALL_DIR/.env"
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  mv "/tmp/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  echo "==> Starting service"
  systemctl restart "$SERVICE_NAME" || true
else
  echo "==> systemd not detected; skipping service installation"
  echo "    To start manually: $INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py"
fi

# 8. Done
echo ""
echo "==============================================="
echo "DockLiner setup complete."
echo "Install dir : $INSTALL_DIR"
echo "Config file : $INSTALL_DIR/.env"
echo "Service     : $SERVICE_NAME"
if command -v systemctl &>/dev/null; then
  echo "Status      : systemctl status $SERVICE_NAME"
  echo "Logs        : journalctl -u $SERVICE_NAME -f"
fi
WEB_PORT=$(grep -E '^DOCKLINER_PORT=' "$INSTALL_DIR/.env" | cut -d'=' -f2 || echo "50021")
echo "Web UI      : http://$(hostname -I | awk '{print $1}'):$WEB_PORT"
echo "Default user: root / qwer.1234"
echo "==============================================="
echo "Change the default password in Settings → Config after first login."
