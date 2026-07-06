from pathlib import Path
from typing import Dict, List
import os

COMPOSE_CANDIDATES = ["compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"]
ENV_CANDIDATES = [".env", "env", "ENV"]
EXAMPLE_ENV_CANDIDATES = [".env.example", "env.example", ".env.sample", "env.sample", ".env.template", "env.template"]

def _read(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def scan_downloaded_repo(root: str) -> Dict:
    r = Path(root)
    env = ""
    env_path = ""
    example = ""
    example_path = ""
    for name in ENV_CANDIDATES:
        p = r / name
        if p.exists():
            env = _read(p)
            env_path = str(p.relative_to(r))
            break
    for name in EXAMPLE_ENV_CANDIDATES:
        p = r / name
        if p.exists():
            example = _read(p)
            example_path = str(p.relative_to(r))
            break

    dockerfile_p = r / "Dockerfile"
    dockerfile = _read(dockerfile_p)

    compose = ""
    compose_path = ""
    compose_file = None
    for name in COMPOSE_CANDIDATES:
        p = r / name
        compose = _read(p)
        if compose:
            compose_path = str(p.relative_to(r))
            compose_file = name
            break

    files = [str(p.relative_to(r)) for p in r.rglob("*") if p.is_file()]
    size_bytes = sum(os.path.getsize(p) for p in r.rglob("*") if p.is_file()) if r.exists() else 0

    repo_name = r.name

    return {
        "root": str(r),
        "env": env,
        "env_path": env_path,
        "example_env": example,
        "example_env_path": example_path,
        "dockerfile": dockerfile,
        "dockerfile_exists": bool(dockerfile),
        "compose": compose,
        "compose_path": str(compose_path) if compose_path else "",
        "compose_exists": bool(compose),
        "compose_file": compose_file,
        "files": files,
        "size_bytes": size_bytes,
        "repo_name": repo_name,
    }


def scan_local_dir(path: str) -> Dict:
    """Alias for scanning any existing local directory."""
    return scan_downloaded_repo(path)
