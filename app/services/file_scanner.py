from pathlib import Path
from typing import Dict, List

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
            env_path = str(p)
            break
    for name in EXAMPLE_ENV_CANDIDATES:
        p = r / name
        if p.exists():
            example = _read(p)
            example_path = str(p)
            break

    dockerfile = _read(r / "Dockerfile")
    compose = _read(r / "docker-compose.yml")
    if not compose:
        compose = _read(r / "docker-compose.yaml")

    files = [str(p.relative_to(r)) for p in r.rglob("*") if p.is_file()]

    return {
        "root": str(r),
        "env": env,
        "env_path": env_path,
        "example_env": example,
        "example_env_path": example_path,
        "dockerfile": dockerfile,
        "dockerfile_exists": bool(dockerfile),
        "compose": compose,
        "compose_exists": bool(compose),
        "files": files,
    }
