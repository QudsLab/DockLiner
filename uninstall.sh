#!/usr/bin/env bash
# DockLiner uninstaller for Linux/macOS/WSL
set -e

INSTALL_DIR="/opt/dockliner"
SERVICE_NAME="dockliner"

if [ -n "$DOCKLINER_INSTALL_DIR" ]; then
  INSTALL_DIR="$DOCKLINER_INSTALL_DIR"
fi

echo "==> DockLiner uninstall"
echo "Install dir: $INSTALL_DIR"

# 1. Stop and disable service if systemd is available
if command -v systemctl &>/dev/null; then
  if systemctl list-unit-files | grep -q "^$SERVICE_NAME.service"; then
    echo "==> Stopping systemd service: $SERVICE_NAME"
    systemctl stop "$SERVICE_NAME" || true
    systemctl disable "$SERVICE_NAME" || true
    rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload || true
  fi
fi

# 2. Keep live DB if requested
if [ -f "$INSTALL_DIR/.env" ]; then
  if [ "${DOCKLINER_KEEP_DB:-}" != "1" ]; then
    DB_TYPE=$(grep -E '^DOCKLINER_DB_TYPE=' "$INSTALL_DIR/.env" | cut -d'=' -f2 || echo "sqlite")
    if [ "$DB_TYPE" != "sqlite" ] && [ -d "$INSTALL_DIR/db" ]; then
      echo "==> Live DB detected in $INSTALL_DIR/db — keeping it (remove manually if you want it gone)."
    fi
  fi
fi

# 3. Remove install directory
if [ -d "$INSTALL_DIR" ]; then
  echo "==> Removing $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
fi

# 4. Delete this uninstall script if run from outside install dir
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
if [ -f "$SCRIPT_PATH" ]; then
  echo "==> Removing uninstall script"
  rm -f "$SCRIPT_PATH"
fi

echo "==> DockLiner removed."
