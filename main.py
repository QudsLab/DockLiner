#!/usr/bin/env python3
import sys
from pathlib import Path

# If .env is missing, create a default one from env_maker before any config import.
env_path = Path(".env")
if not env_path.exists():
    try:
        from app.env_maker import refine_env
        env_path.write_text(refine_env(""), encoding="utf-8")
        print("[DockLiner] .env was missing. Created default .env.")
    except Exception as e:
        print(f"[DockLiner] Could not create default .env: {e}")

# Import app after env check.
from app.main import create_app

app = create_app()

import uvicorn
from app.core.config import settings, resolve_port, resolve_hosts

if __name__ == "__main__":
    port = resolve_port()
    host = resolve_hosts()[0]
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True,
        reload_dirs=["app"],
        reload_includes=["*.py", "*.html", "*.css"],
        reload_excludes=["downloads", "github-cache", "projects", "doc", "__pycache__", "*.db", "*.log"],
    )
