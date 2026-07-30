import threading
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from pathlib import Path
import io, zipfile, json, os, urllib.request, urllib.error, subprocess, time, sys
from app.core.db import get_db, SessionLocal
from app.core.config import settings, log_login_attempt, log_login_success, log_login_failure
from app.core.auth import verify, login_user, logout_user, get_session_user, require_auth
from app.models.project import (
    Project, Deployment, AccessToken, GithubCache, SavedOrg, Download,
    HealthCheck, Metric, AuditLog, Webhook, Notification, ErrorLog, SystemLog
)
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectOut,
    DeploymentOut, AccessTokenCreate, AccessTokenOut,
    ProjectFileUpdate, ProjectFilesOut, DeployLogOut,
    DirectCreatePayload,
)
from app.schemas.monitoring import (
    HealthCheckCreate, HealthCheckUpdate, HealthCheckOut,
    MetricOut, AuditLogOut, WebhookCreate, WebhookOut, NotificationOut,
)
from app.services.dockliner_service import DockLinerService
from app.services.deploy_service import DeployService
from app.services.github_download_service import GitHubDownloadService
from app.services.log_service import LogService
from app.services.terminal_service import TerminalService
from app.services.monitoring_service import MonitoringService, AuditService, RateLimitService
from app.services.file_scanner import scan_downloaded_repo, scan_local_dir
from app.services.error_log_service import ErrorLogService
import yaml, urllib.parse, shutil
import re


from app.env_maker import refine_env, validate_env_content


def _sanitize_project_name(name: str) -> str:
    """Turn a repo/branch/path string into a safe unique-ish project name."""
    if not name:
        return ""
    # Replace separators and risky chars with underscores.
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    # Collapse multiple underscores and strip ends.
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return cleaned[:100]


def _extract_host_port_from_compose(content: str, env: Optional[dict] = None) -> Optional[int]:
    """Parse compose YAML and return the first host port found in services.*.ports.
    Resolves simple ${VAR:-default} variable substitution using provided env dict."""
    if not content:
        return None
    env = env or {}
    try:
        doc = yaml.safe_load(content)
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    services = doc.get("services") or {}
    if not isinstance(services, dict):
        return None
    var_re = re.compile(r"\$\{([^}]+)\}")

    def resolve_value(value):
        if not isinstance(value, str):
            return value
        def repl(match):
            expr = match.group(1)
            if ":-" in expr:
                var, default = expr.split(":-", 1)
            elif "-" in expr:
                var, default = expr.split("-", 1)
            else:
                var, default = expr, ""
            return str(env.get(var, default))
        return var_re.sub(repl, value)

    for svc in services.values():
        if not isinstance(svc, dict):
            continue
        ports = svc.get("ports") or []
        if not isinstance(ports, list):
            continue
        for entry in ports:
            if isinstance(entry, int):
                return entry
            if isinstance(entry, str):
                resolved = resolve_value(entry)
                host_part = resolved.split(":")[-2] if resolved.count(":") >= 2 else resolved.split(":")[0]
                host_part = host_part.split("/")[0].strip()
                if host_part.isdigit():
                    return int(host_part)
            if isinstance(entry, dict):
                published = entry.get("published") or entry.get("target")
                if isinstance(published, (int, str)):
                    published = resolve_value(published)
                if isinstance(published, int):
                    return published
                if isinstance(published, str) and published.isdigit():
                    return int(published)
    return None


def _load_env_dict(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"\'')
    except Exception:
        pass
    return env



class TerminalCommand(BaseModel):
    command: str = ""
    cwd: Optional[str] = None

router = APIRouter(prefix="/api", tags=["api"])

class LoginBody(BaseModel):
    user: str
    pass_: str = Field(..., alias="pass")

@router.post("/login")
def api_login(data: LoginBody, response: Response, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")
    log_login_attempt(data.user, ip, ua)
    if not RateLimitService.limit_login(ip):
        AuditService.log(db, "login_denied", target=data.user, details="rate limited", ip=ip, user_agent=ua)
        log_login_failure(data.user, ip, ua, reason="rate_limited")
        raise HTTPException(status_code=429, detail="Too many login attempts")
    if verify(data.user, data.pass_):
        for k, v in login_user(data.user).items():
            response.set_cookie(k, v, httponly=True, samesite="lax")
        AuditService.log(db, "login", target=data.user, details="success", user=data.user, ip=ip, user_agent=ua)
        log_login_success(data.user, ip, ua)
        return {"ok": True}
    AuditService.log(db, "login_failed", target=data.user, details="bad password", ip=ip, user_agent=ua)
    log_login_failure(data.user, ip, ua, reason="bad_password")
    raise HTTPException(status_code=401, detail="Invalid credentials")

@router.post("/logout")
def api_logout(response: Response, request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request)
    ip = request.client.host if request.client else ""
    AuditService.log(db, "logout", target=user, user=user, ip=ip)
    for k, v in logout_user().items():
        response.set_cookie(k, v, httponly=True, samesite="lax")
    return {"ok": True}

# ---------- Projects ----------

@router.get("/projects", response_model=List[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return db.query(Project).all()

@router.post("/projects", response_model=ProjectOut)
def create_project(data: ProjectCreate, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    """Create a new project from GitHub or local/download source."""
    name = data.name or data.repo
    if not name:
        raise HTTPException(status_code=400, detail="Project name required")
    existing = db.query(Project).filter(Project.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Project name already exists")

    deploy_path = str(Path(settings.PROJECTS_DIR) / name)
    p = Project(
        name=name,
        github_repo_url=f"https://github.com/{data.owner}/{data.repo}.git" if data.owner and data.repo else "",
        branch=data.branch or "main",
        deploy_path=deploy_path,
        compose_file=data.compose_file or "docker-compose.yml",
        deploy_method="compose",
        command_mode="compose",
        source_type=data.source or "github",
        source_path=data.local_path or "",
        env_vars=data.env_vars or {},
        env_content=data.env_content or "",
        compose_content=data.compose_content or "",
        dockerfile_content=data.dockerfile_content or "",
        token_id=data.token_id,
        labels=data.labels or "",
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    # Copy source files into deploy path.
    src = Path(p.source_path) if p.source_path else None
    ppath = Path(deploy_path)
    if ppath.exists():
        shutil.rmtree(ppath, ignore_errors=True)
    if data.source == "github" and data.owner and data.repo:
        GithubCacheService.download_and_extract(p, db)
    elif src and src.exists():
        shutil.copytree(src, ppath)
        # If source was a download, normalize the nested folder structure.
        if p.source_type == "download":
            top = next((x for x in ppath.iterdir() if x.is_dir()), None)
            if top and (top / "docker-compose.yml").exists():
                for f in top.iterdir():
                    dest = ppath / f.name
                    if dest.exists():
                        if dest.is_dir(): shutil.rmtree(dest)
                        else: dest.unlink()
                    shutil.move(str(f), str(dest))
                shutil.rmtree(top)
    else:
        ppath.mkdir(parents=True, exist_ok=True)

    # Overwrite with editor-provided content.
    env_txt = str(p.env_content or "")
    if len(env_txt):
        (ppath / ".env").write_text(env_txt, encoding="utf-8")
    compose_mode = str(p.command_mode)
    if compose_mode == "compose" and len(str(p.compose_content or "")):
        (ppath / str(p.compose_file)).write_text(str(p.compose_content), encoding="utf-8")
    if compose_mode == "dockerfile" and len(str(p.dockerfile_content or "")):
        (ppath / "Dockerfile").write_text(str(p.dockerfile_content), encoding="utf-8")
    if compose_mode == "direct" and len(str(p.direct_command or "")):
        (ppath / "run.sh").write_text(str(p.direct_command), encoding="utf-8")
    AuditService.log(db, "project_create", target=p.name, user=user)
    return p

class QuickCreatePayload(BaseModel):
    download_id: int
    name: Optional[str] = None

@router.post("/projects/quick-create", response_model=ProjectOut)
def quick_create_project(data: QuickCreatePayload, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    """Create a project directly from a download — no editor step, no DockLiner config edits."""
    dl = db.query(Download).filter(Download.id == data.download_id).first()
    if not dl or not dl.extracted_path:
        raise HTTPException(status_code=404, detail="Download not ready")
    src = Path(dl.extracted_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source path missing")

    name = data.name or dl.repo or src.name
    existing = db.query(Project).filter(Project.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Project name exists")

    deploy_path = str(Path(settings.PROJECTS_DIR) / name)
    p = Project(
        name=name,
        github_repo_url=f"https://github.com/{dl.owner}/{dl.repo}.git" if dl.owner and dl.repo else "",
        branch=dl.ref or "main",
        deploy_path=deploy_path,
        compose_file="docker-compose.yml",
        deploy_method="compose",
        command_mode="compose",
        source_type="github",
        source_path=str(src),
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    # Copy all files from download to project without editing.
    ppath = Path(deploy_path)
    if ppath.exists():
        shutil.rmtree(ppath, ignore_errors=True)
    shutil.copytree(src, ppath)

    AuditService.log(db, "project_quick_create", target=p.name, user=user)
    return p


class DirectCreatePayload(BaseModel):
    source: str
    download_id: Optional[int] = None
    path: Optional[str] = None
    name: Optional[str] = None

@router.post("/projects/direct-create", response_model=ProjectOut)
def direct_create_project(data: DirectCreatePayload, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    """Create a project by copying a source as-is. No compose/env editing step."""
    source = data.source
    src_path = None
    github_url = ""
    branch = "main"
    release_tag = None
    token_id = None
    suggested_name = (data.name or "").strip()
    dl = None

    if source == "download":
        dl = db.query(Download).filter(Download.id == data.download_id).first() if data.download_id else None
        if not dl or not dl.extracted_path:
            raise HTTPException(status_code=404, detail="Download not ready")
        src_path = dl.extracted_path
        suggested_name = suggested_name or (f"{dl.owner}_{dl.repo}_{dl.ref}" if dl.owner and dl.repo else dl.repo or Path(src_path).name)
        github_url = f"https://github.com/{dl.owner}/{dl.repo}.git" if dl.owner and dl.repo else ""
        branch = dl.ref or "main"
        token_id = dl.token_id
    elif source == "local":
        decoded_path = urllib.parse.unquote(data.path or "")
        if not decoded_path:
            raise HTTPException(status_code=400, detail="Path required")
        src = Path(decoded_path)
        if not src.exists():
            raise HTTPException(status_code=400, detail="Directory does not exist")
        src_path = str(src)
        suggested_name = suggested_name or src.name
    elif source == "github":
        dl = db.query(Download).filter(Download.id == data.download_id).first() if data.download_id else None
        if not dl or not dl.extracted_path:
            raise HTTPException(status_code=404, detail="Download not ready")
        src_path = dl.extracted_path
        suggested_name = suggested_name or (f"{dl.owner}_{dl.repo}_{dl.ref}" if dl.owner and dl.repo else dl.repo or Path(src_path).name)
        github_url = f"https://github.com/{dl.owner}/{dl.repo}.git" if dl.owner and dl.repo else ""
        branch = dl.ref or "main"
        token_id = dl.token_id
    else:
        raise HTTPException(status_code=400, detail="Invalid source")

    name = _sanitize_project_name(suggested_name)
    if not name:
        raise HTTPException(status_code=400, detail="Could not determine project name")

    existing = db.query(Project).filter(Project.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Project name exists")

    deploy_path = str(Path(settings.PROJECTS_DIR) / name)

    # Auto-detect command mode from source files; do not modify any file.
    scan = scan_local_dir(src_path)
    compose_file = scan.get("compose_file") or "docker-compose.yml"
    compose_exists = bool(scan.get("compose_exists"))
    dockerfile_exists = bool(scan.get("dockerfile_exists"))
    if compose_exists:
        command_mode = "compose"
        deploy_method = "compose"
    elif dockerfile_exists:
        command_mode = "dockerfile"
        deploy_method = "build"
    else:
        command_mode = "direct"
        deploy_method = "direct"

    port = _extract_host_port_from_compose(scan.get("compose", ""))
    if port is None:
        raise HTTPException(status_code=400, detail="No host port declared in docker-compose.yml. Add a ports mapping like '50021:3000'.")

    p = Project(
        name=name,
        github_repo_url=github_url,
        branch=branch,
        deploy_path=deploy_path,
        compose_file=compose_file,
        env_vars={},
        env_content="",
        example_env_content="",
        dockerfile_content="",
        compose_content="",
        labels="",
        token_id=token_id,
        deploy_method=deploy_method,
        release_tag=release_tag,
        command_mode=command_mode,
        raw_mode=False,
        direct_command="",
        source_type=source,
        source_path=src_path,
        deploy_commands=[],
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    # Copy source as-is; never edit files automatically.
    ppath = Path(deploy_path)
    if ppath.exists():
        shutil.rmtree(ppath, ignore_errors=True)
    shutil.copytree(src_path, ppath)

    AuditService.log(db, "project_direct_create", target=p.name, user=user)
    return p

@router.get("/projects/{pid}", response_model=ProjectOut)
def get_project(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return p

@router.patch("/projects/{pid}", response_model=ProjectOut)
def update_project(pid: int, data: ProjectUpdate, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    payload = data.model_dump(exclude_unset=True)
    payload.pop("port", None)
    new_name = payload.pop("name", None)
    for k, v in payload.items():
        setattr(p, k, v)
    if new_name is not None and new_name != p.name:
        existing = db.query(Project).filter(Project.name == new_name, Project.id != pid).first()
        if existing:
            raise HTTPException(status_code=409, detail="Project name already exists")
        old_path = Path(str(p.deploy_path)) if p.deploy_path else None
        new_deploy_path = str(Path(settings.PROJECTS_DIR) / new_name)
        new_path = Path(new_deploy_path)
        if old_path and old_path.exists() and not new_path.exists():
            old_path.rename(new_path)
        p.name = new_name
        p.deploy_path = new_deploy_path
    db.commit()
    db.refresh(p)
    AuditService.log(db, "project_update" if not new_name else "project_rename", target=p.name, user=user)
    return p

@router.delete("/projects/{pid}")
def delete_project(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    from app.services.deploy_service import DeployService
    if p.deploy_path:
        DeployService._remove_tree(Path(p.deploy_path))
    db.query(Deployment).filter(Deployment.project_id == pid).delete()
    db.delete(p)
    db.commit()
    AuditService.log(db, "project_delete", target=p.name, user=user)
    return {"ok": True}

@router.post("/projects/{pid}/build")
def build_project(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail='Not found')
    tok = None
    if p.token_id:
        tok = db.query(AccessToken).filter(AccessToken.id == p.token_id).first()
    if not tok:
        tok = db.query(AccessToken).first()
    dep = DeployService.build(p, tok.token if tok else None)
    db_dep = Deployment(project_id=p.id, status="success" if dep else "error", logs="\n".join(dep))
    db.add(db_dep)
    db.commit()
    db.refresh(db_dep)
    return {'deployment_id': db_dep.id, 'status': db_dep.status}

@router.post("/projects/{pid}/deploy")
def deploy_project(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail='Not found')
    tok = None
    if p.token_id:
        tok = db.query(AccessToken).filter(AccessToken.id == p.token_id).first()
    if not tok:
        tok = db.query(AccessToken).first()
    dep = DeployService.deploy_project(p, tok.token if tok else None, db)
    return {'deployment_id': dep.id, 'status': dep.status}

@router.get("/projects/{pid}/deploy-preview")
def deploy_preview(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail='Not found')
    return {'commands': p.deploy_commands or DeployService.preview_commands(p)}

@router.post("/projects/{pid}/run")
def run_project(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail='Not found')
    dep = DeployService.up(p)
    db_dep = Deployment(project_id=p.id, status="success" if dep else "error", logs="\n".join(dep))
    db.add(db_dep)
    db.commit()
    db.refresh(db_dep)
    return {'deployment_id': db_dep.id, 'status': db_dep.status}

@router.post("/projects/{pid}/start")
def start_project(pid: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail='Not found')
    rc, out = DockLinerService.compose_up(str(p.deploy_path), p.compose_file)
    p.status = "running" if rc == 0 else "error"
    db.commit()
    AuditService.log(db, "start", target=p.name, user=user, ip=request.client.host if request.client else "")
    return {"status": p.status, "output": out}

@router.post("/projects/{pid}/stop")
def stop_project(pid: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    rc, out = DockLinerService.compose_down(str(p.deploy_path), p.compose_file)
    p.status = "stopped" if rc == 0 else "error"
    db.commit()
    AuditService.log(db, "stop", target=p.name, user=user, ip=request.client.host if request.client else "")
    return {"status": p.status, "output": out}

@router.post("/projects/{pid}/restart")
def restart_project(pid: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    DockLinerService.compose_down(str(p.deploy_path), p.compose_file)
    rc, out = DockLinerService.compose_up(str(p.deploy_path), p.compose_file)
    p.status = "running" if rc == 0 else "error"
    db.commit()
    AuditService.log(db, "restart", target=p.name, user=user, ip=request.client.host if request.client else "")
    return {"status": p.status, "output": out}

@router.get("/projects/{pid}/logs")
def project_logs(pid: int, tail: int = 200, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return {"logs": DockLinerService.compose_logs(str(p.deploy_path), p.compose_file, tail=tail)}

@router.get("/projects/{pid}/deployments", response_model=List[DeploymentOut])
def list_deployments(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return db.query(Deployment).filter(Deployment.project_id == pid).order_by(Deployment.timestamp.desc()).all()

@router.get("/projects/{pid}/deploy-logs", response_model=List[DeployLogOut])
def deploy_logs(pid: int, limit: int = 50, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return db.query(Deployment).filter(Deployment.project_id == pid).order_by(Deployment.timestamp.desc()).limit(limit).all()

@router.get("/projects/{pid}/files", response_model=ProjectFilesOut)
def list_project_files(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    root = Path(p.deploy_path)
    if not root.exists():
        return {"files": []}
    files = []
    for path in sorted(root.rglob("*")):
        try:
            rel = path.relative_to(root).as_posix()
            files.append({
                "path": rel,
                "size": path.stat().st_size if path.is_file() else 0,
                "is_dir": path.is_dir(),
            })
        except Exception:
            continue
    return {"files": files}

class ProjectFileUpdate(BaseModel):
    content: str

class MoveFilePayload(BaseModel):
    source: str
    destination: str

@router.post("/projects/{pid}/files/move")
def move_project_file(pid: int, payload: MoveFilePayload, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    root = Path(p.deploy_path).resolve()
    src = (Path(p.deploy_path) / payload.source).resolve()
    dst = (Path(p.deploy_path) / payload.destination).resolve()
    try:
        src.relative_to(root)
        dst.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source not found")
    if dst.exists():
        raise HTTPException(status_code=409, detail="Destination already exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)
    AuditService.log(db, "project_file_move", target=f"{p.name}: {payload.source} -> {payload.destination}", user=user)
    return {"ok": True}

@router.post("/projects/{pid}/files/copy")
def copy_project_file(pid: int, payload: MoveFilePayload, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    root = Path(p.deploy_path).resolve()
    src = (Path(p.deploy_path) / payload.source).resolve()
    dst = (Path(p.deploy_path) / payload.destination).resolve()
    try:
        src.relative_to(root)
        dst.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not src.exists():
        raise HTTPException(status_code=404, detail="Source not found")
    if dst.exists():
        raise HTTPException(status_code=409, detail="Destination already exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    AuditService.log(db, "project_file_copy", target=f"{p.name}: {payload.source} -> {payload.destination}", user=user)
    return {"ok": True}

@router.get("/projects/{pid}/files/{path:path}")
def read_project_file(pid: int, path: str, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    target = Path(p.deploy_path) / path
    target = target.resolve()
    root = Path(p.deploy_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        return {"path": path, "is_dir": True}
    return {"path": path, "content": target.read_text(encoding="utf-8", errors="replace"), "is_dir": False, "size": target.stat().st_size}

@router.put("/projects/{pid}/files/{path:path}")
def update_project_file(pid: int, path: str, data: ProjectFileUpdate, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    target = (Path(p.deploy_path) / path).resolve()
    root = Path(p.deploy_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data.content, encoding="utf-8")
    # Mirror to DB fields for main config files
    lower = path.lower()
    if lower in ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"):
        p.compose_content = data.content
        p.compose_file = path
        parsed_port = _extract_host_port_from_compose(data.content)
        if parsed_port is not None:
            pass  # DockLiner no longer stores ports from compose; container runtime is the source of truth.
    elif lower == "dockerfile":
        p.dockerfile_content = data.content
    elif lower in (".env", "env"):
        p.env_content = data.content
    db.commit()
    AuditService.log(db, "project_file_update", target=f"{p.name}/{path}", user=user)
    return {"ok": True}

@router.post("/projects/{pid}/files/{path:path}")
def create_project_file(pid: int, path: str, data: ProjectFileUpdate, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    target = (Path(p.deploy_path) / path).resolve()
    root = Path(p.deploy_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if target.exists():
        raise HTTPException(status_code=409, detail="Already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data.content, encoding="utf-8")
    AuditService.log(db, "project_file_create", target=f"{p.name}/{path}", user=user)
    return {"ok": True}

@router.post("/projects/{pid}/mkdir/{path:path}")
def create_project_folder(pid: int, path: str, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    target = (Path(p.deploy_path) / path).resolve()
    root = Path(p.deploy_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if target.exists():
        raise HTTPException(status_code=409, detail="Already exists")
    target.mkdir(parents=True, exist_ok=False)
    AuditService.log(db, "project_folder_create", target=f"{p.name}/{path}", user=user)
    return {"ok": True}

@router.delete("/projects/{pid}/files/{path:path}")
def delete_project_file(pid: int, path: str, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    target = (Path(p.deploy_path) / path).resolve()
    root = Path(p.deploy_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.is_dir():
        import shutil
        shutil.rmtree(target)
    else:
        target.unlink()
    AuditService.log(db, "project_file_delete", target=f"{p.name}/{path}", user=user)
    return {"ok": True}


@router.get("/projects/{pid}/health")
def project_health(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    hc = db.query(HealthCheck).filter(HealthCheck.project_id == pid).first()
    if not hc:
        return {"enabled": False}
    return {"enabled": hc.enabled, "last_status": hc.last_status, "last_check": hc.last_check, "latency_ms": hc.last_latency_ms}

@router.get("/projects/{pid}/metrics")
def project_metrics(pid: int, metric_type: str = "cpu_percent", db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rows = MonitoringService.get_project_metrics(db, pid, metric_type, limit=200)
    return {"metric_type": metric_type, "points": rows}

@router.get("/projects/{pid}/timeline")
def project_timeline(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    deps = db.query(Deployment).filter(Deployment.project_id == pid).order_by(Deployment.timestamp.desc()).limit(50).all()
    audits = db.query(AuditLog).filter(AuditLog.target == str(pid)).order_by(AuditLog.timestamp.desc()).limit(50).all()
    return {"deployments": [{"id": d.id, "timestamp": d.timestamp, "status": d.status} for d in deps],
            "events": [{"action": a.action, "timestamp": a.timestamp, "user": a.user} for a in audits]}

# ---------- Health Checks ----------
@router.post("/health-checks", response_model=HealthCheckOut)
def create_health_check(data: HealthCheckCreate, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    hc = HealthCheck(**data.model_dump())
    db.add(hc)
    db.commit()
    db.refresh(hc)
    return hc

@router.get("/health-checks", response_model=List[HealthCheckOut])
def list_health_checks(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return db.query(HealthCheck).all()

@router.patch("/health-checks/{hid}", response_model=HealthCheckOut)
def update_health_check(hid: int, data: HealthCheckUpdate, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    hc = db.query(HealthCheck).filter(HealthCheck.id == hid).first()
    if not hc:
        raise HTTPException(status_code=404, detail="Not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(hc, k, v)
    db.commit()
    db.refresh(hc)
    return hc

@router.post("/health-checks/{hid}/run")
def run_health_check(hid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    hc = db.query(HealthCheck).filter(HealthCheck.id == hid).first()
    if not hc:
        raise HTTPException(status_code=404, detail="Not found")
    r = MonitoringService.run_health_check({"protocol": hc.protocol, "host": hc.host, "port": hc.port, "path": hc.path})
    hc.last_check = datetime.utcnow()
    hc.last_status = r["status"]
    hc.last_latency_ms = r["latency_ms"]
    db.commit()
    if r["status"] != "up":
        webhooks = db.query(Webhook).filter(Webhook.enabled == True).all()
        for wh in webhooks:
            if "health_fail" in (wh.events or ""):
                MonitoringService.send_webhook(wh.url, "health_fail", {"project_id": hc.project_id, "status": r["status"], "error": r["error"]})
        db.add(Notification(level="error", title=f"Health check failed: project {hc.project_id}", body=r["error"] or "down"))
        db.commit()
    return r

# ---------- Docker ----------

@router.get("/docker/containers")
def list_containers(user: str = Depends(require_auth)):
    return DockLinerService.list_containers()

@router.get("/docker/images")
def list_images(user: str = Depends(require_auth)):
    return DockLinerService.list_images()

@router.get("/docker/networks")
def list_networks(user: str = Depends(require_auth)):
    return DockLinerService.list_networks()

@router.get("/docker/volumes")
def list_volumes(user: str = Depends(require_auth)):
    return DockLinerService.list_volumes()

@router.get("/docker/security")
def docker_security(user: str = Depends(require_auth)):
    return DockLinerService.security_summary()

@router.post("/docker/containers/{cid}/stop")
def stop_container(cid: str, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rc, out = DockLinerService.stop_container(cid)
    AuditService.log(db, "container_stop", target=cid, user=user, ip=request.client.host if request.client else "")
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.post("/docker/containers/{cid}/remove")
def remove_container(cid: str, request: Request, force: bool = False, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rc, out = DockLinerService.remove_container(cid, force)
    AuditService.log(db, "container_remove", target=cid, user=user, ip=request.client.host if request.client else "")
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.post("/docker/images/{iid}/remove")
def remove_image(iid: str, request: Request, force: bool = False, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rc, out = DockLinerService.remove_image(iid, force)
    AuditService.log(db, "image_remove", target=iid, user=user, ip=request.client.host if request.client else "")
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.get("/docker/containers/{cid}/ports")
def container_ports(cid: str, user: str = Depends(require_auth)):
    return DockLinerService.inspect_container_ports(cid)

@router.get("/docker/containers/{cid}/logs")
def container_logs(cid: str, tail: int = 200, user: str = Depends(require_auth)):
    return {"logs": DockLinerService.container_logs(cid, tail)}

@router.get("/docker/containers/{cid}/top")
def container_top(cid: str, user: str = Depends(require_auth)):
    return DockLinerService.container_top(cid)

# ---------- GitHub API via token ----------

def _github_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json", "User-Agent": "DockLiner"}

def _github_get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers=_github_headers(token))
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _github_get_with_headers(url: str, token: str) -> tuple:
    req = urllib.request.Request(url, headers=_github_headers(token))
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        scopes = resp.headers.get("X-OAuth-Scopes", "")
        return data, scopes

def _cache_get_or_fetch(db: Session, token_id: int, endpoint: str, url: str, token: str, ttl_seconds: int = 600) -> list:
    cached = db.query(GithubCache).filter(GithubCache.token_id == token_id, GithubCache.endpoint == endpoint).first()
    if cached:
        age = (datetime.utcnow() - cached.created_at).total_seconds()
        if age < ttl_seconds:
            try:
                return json.loads(str(cached.payload_json))
            except Exception:
                pass
    data = _github_get(url, token)
    payload = json.dumps(data) if isinstance(data, list) else json.dumps([data])
    if cached:
        cached.payload_json = payload
        cached.created_at = datetime.utcnow()
    else:
        db.add(GithubCache(token_id=token_id, endpoint=endpoint, payload_json=payload))
    db.commit()
    return data if isinstance(data, list) else [data]

@router.get("/github/token/{token_id}/orgs")
def github_orgs(token_id: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    tok = db.query(AccessToken).filter(AccessToken.id == token_id).first()
    if not tok:
        raise HTTPException(status_code=404, detail="Token not found")
    token_str = str(tok.token)
    # user profile
    profile = _github_get("https://api.github.com/user", token_str)
    orgs = _cache_get_or_fetch(db, token_id, "orgs", "https://api.github.com/user/orgs?per_page=100", token_str)
    saved = db.query(SavedOrg).filter(SavedOrg.token_id == token_id).all()
    saved_logins = {s.org_login for s in saved}
    out = [{"login": profile.get("login"), "type": "user", "avatar_url": profile.get("avatar_url"), "saved": profile.get("login") in saved_logins}]
    for o in orgs:
        out.append({"login": o.get("login"), "type": "org", "avatar_url": o.get("avatar_url"), "saved": o.get("login") in saved_logins})
    return out

@router.get("/github/token/{token_id}/repos")
def github_repos(token_id: int, org: str, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    tok = db.query(AccessToken).filter(AccessToken.id == token_id).first()
    if not tok:
        raise HTTPException(status_code=404, detail="Token not found")
    token_str = str(tok.token)
    profile = _github_get("https://api.github.com/user", token_str)
    owner_login = profile.get("login", "")
    is_self = org.lower() == owner_login.lower()
    scopes = ""
    if is_self:
        # Personal repos: authenticated endpoint for public+private
        url = "https://api.github.com/user/repos?per_page=100&sort=updated&affiliation=owner,collaborator,organization_member"
        repos, scopes = _github_get_with_headers(url, token_str)
    else:
        # Try org endpoint first (shows private repos if token is a member)
        try:
            org_url = f"https://api.github.com/orgs/{org}/repos?per_page=100&sort=updated"
            repos, scopes = _github_get_with_headers(org_url, token_str)
        except Exception:
            repos, scopes = [], ""
        # Fall back to public user endpoint
        if not repos:
            try:
                pub_url = f"https://api.github.com/users/{org}/repos?per_page=100&sort=updated"
                repos, scopes = _github_get_with_headers(pub_url, token_str)
            except Exception:
                repos, scopes = [], ""
    out = []
    has_private = False
    for r in repos:
        if r.get("private"):
            has_private = True
        out.append({
            "id": r.get("id"),
            "name": r.get("name"),
            "full_name": r.get("full_name"),
            "description": r.get("description") or "",
            "private": r.get("private"),
            "html_url": r.get("html_url"),
            "clone_url": r.get("clone_url"),
            "default_branch": r.get("default_branch"),
            "stargazers_count": r.get("stargazers_count", 0),
            "language": r.get("language") or "",
            "updated_at": r.get("updated_at"),
        })
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    repo_scope_ok = "repo" in scope_list or "repo:read" in scope_list
    return {
        "repos": out,
        "has_private": has_private,
        "scopes": scope_list,
        "repo_scope_ok": repo_scope_ok,
        "count": len(out),
    }

@router.get("/github/users/{username}")
def github_user_profile(username: str, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    tok = db.query(AccessToken).first()
    if not tok:
        raise HTTPException(status_code=404, detail="No token configured")
    token_str = str(tok.token)
    try:
        data = _github_get(f"https://api.github.com/users/{username}", token_str)
        return {
            "login": data.get("login"),
            "type": data.get("type", "user"),
            "avatar_url": data.get("avatar_url"),
            "name": data.get("name") or data.get("login"),
            "public_repos": data.get("public_repos", 0),
            "html_url": data.get("html_url"),
            "found": True,
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"found": False, "login": username}
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/github/repos/{owner}/{repo}/branches")
def github_branches(owner: str, repo: str, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    # Need a token — use first available
    tok = db.query(AccessToken).first()
    if not tok:
        raise HTTPException(status_code=404, detail="No token configured")
    token_str = str(tok.token)
    data = _github_get(f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100", token_str)
    return [{"name": b.get("name"), "commit_sha": b.get("commit", {}).get("sha", "")[:7]} for b in data]

@router.get("/github/repos/{owner}/{repo}/releases")
def github_releases(owner: str, repo: str, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    tok = db.query(AccessToken).first()
    if not tok:
        raise HTTPException(status_code=404, detail="No token configured")
    token_str = str(tok.token)
    data = _github_get(f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=100", token_str)
    return [{
        "id": r.get("id"),
        "tag_name": r.get("tag_name"),
        "name": r.get("name"),
        "published_at": r.get("published_at"),
        "prerelease": r.get("prerelease"),
        "draft": r.get("draft"),
        "body": (r.get("body") or "")[:200],
    } for r in data]

@router.post("/github/download")
def github_download(body: dict, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    token_id = body.get("token_id")
    owner = body.get("owner")
    repo = body.get("repo")
    ref = body.get("ref")
    if not token_id or not owner or not repo or not ref:
        raise HTTPException(status_code=400, detail="Missing token_id, owner, repo, or ref")
    tok = db.query(AccessToken).filter(AccessToken.id == token_id).first()
    if not tok:
        raise HTTPException(status_code=404, detail="Token not found")
    dl = GitHubDownloadService.create_download(db, token_id, owner, repo, ref)
    token_str = str(tok.token)
    # Run download in background thread so the UI can poll progress
    def progress(_dl):
        pass
    thread = threading.Thread(
        target=GitHubDownloadService.run_download,
        args=(dl.id, token_str, SessionLocal, progress),
        daemon=True,
    )
    thread.start()
    return {"download_id": dl.id, "status": dl.status, "owner": owner, "repo": repo, "ref": ref}

@router.get("/downloads")
def api_downloads(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    items = DockLinerService.list_downloads(db)
    # Backfill hashes for existing downloads whose zip still exists
    for item in items:
        if item.get("status") == "done" and item.get("download_path") and not item.get("md5_hash"):
            dl = db.query(Download).filter(Download.id == item["id"]).first()
            if dl:
                GitHubDownloadService.backfill_hashes(dl, db)
                item["md5_hash"] = dl.md5_hash
                item["sha256_hash"] = dl.sha256_hash
    return {"downloads": items}

@router.get("/downloads/{dl_id}")
def api_download_detail(dl_id: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    dl = db.query(Download).filter(Download.id == dl_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Download not found")
    out = dl.to_dict()
    out.update(DockLinerService.scan_download(dl))
    return out

@router.delete("/downloads/{dl_id}")
def api_download_delete(dl_id: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    dl = db.query(Download).filter(Download.id == dl_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Download not found")
    DockLinerService.delete_download(dl, db)
    return {"ok": True}

@router.delete("/downloads/folder/{folder_name}")
def api_download_folder_delete(folder_name: str, user: str = Depends(require_auth)):
    if not folder_name or folder_name in (".", "..", "/"):
        raise HTTPException(status_code=400, detail="Invalid folder name")
    ok = DockLinerService.delete_download_folder(folder_name)
    if not ok:
        raise HTTPException(status_code=404, detail="Folder not found or could not be deleted")
    return {"ok": True}

@router.get("/github/download/{dl_id}")
def github_download_status(dl_id: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    dl = db.query(Download).filter(Download.id == dl_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Download not found")
    out = dl.to_dict()
    out.update(GitHubDownloadService.scan(dl))
    return out

@router.delete("/github/download/{dl_id}")
def github_download_delete(dl_id: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    dl = db.query(Download).filter(Download.id == dl_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Download not found")
    GitHubDownloadService.delete_download(dl, db)
    return {"ok": True}

@router.get("/github/downloads")
def github_download_list(limit: int = 50, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rows = db.query(Download).order_by(Download.created_at.desc()).limit(limit).all()
    out = []
    for dl in rows:
        entry = dl.to_dict()
        entry.update(GitHubDownloadService.scan(dl))
        out.append(entry)
    return out


# ---------- Terminal ----------

@router.post("/projects/{pid}/terminal")
def project_terminal_command(pid: int, body: TerminalCommand, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    cwd = body.cwd or str(p.deploy_path)
    # Simple safety: prevent interactive editors or commands that hang without output
    result = TerminalService.exec(pid, body.command, cwd=cwd)
    return result

@router.get("/projects/{pid}/terminal")
def project_terminal_read(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return TerminalService.read(pid)

@router.delete("/projects/{pid}/terminal")
def project_terminal_reset(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    TerminalService.reset(pid, cwd=str(p.deploy_path))
    return {"ok": True}

# ---------- Cleanup ----------

@router.get("/cleanup")
def cleanup_scan(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    from app.services.cleanup_service import CleanupService
    return CleanupService.scan(db)

@router.post("/cleanup/bulk")
def cleanup_bulk(data: Dict[str, Any], db: Session = Depends(get_db), user: str = Depends(require_auth)):
    from app.services.cleanup_service import CleanupService
    items = data.get("items", [])
    result = CleanupService.bulk_delete(items)
    AuditService.log(db, "cleanup_bulk", target=f"deleted={result['deleted']} failed={result['failed']}", user=user)
    return result

# ---------- Tokens ----------

@router.get("/tokens", response_model=List[AccessTokenOut])
def list_tokens(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return db.query(AccessToken).all()

@router.get("/debug/routes")
def debug_routes(request: Request, user: str = Depends(require_auth)):
    from pathlib import Path
    import app.routers.pages as pages_mod
    routes = []
    for r in request.app.routes:
        p = getattr(r, 'path', '')
        n = getattr(r, 'name', '')
        if p:
            routes.append(f"{p} -> {n}")
    return {
        "cwd": str(Path.cwd()),
        "pages_module": pages_mod.__file__,
        "has_setup": any('/projects/setup' in p for p in routes),
        "routes": routes,
    }

@router.post("/tokens", response_model=AccessTokenOut)
def create_token(data: AccessTokenCreate, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    clean_token = (data.token or "").strip()
    if not clean_token:
        raise HTTPException(status_code=400, detail="Token is required")
    t = AccessToken(name=data.name, token=clean_token, provider=data.provider or "github")
    db.add(t)
    db.commit()
    db.refresh(t)
    AuditService.log(db, "token_create", target=t.name, user=user)
    return t

@router.post("/tokens/web")
def create_token_web(
    name: str = Form(...),
    token: str = Form(...),
    provider: str = Form("github"),
    db: Session = Depends(get_db),
    user: str = Depends(require_auth)
):
    clean_token = (token or "").strip()
    if not clean_token:
        return RedirectResponse(url="/settings?token_error=empty#tokens", status_code=303)
    t = AccessToken(name=name, token=clean_token, provider=provider or "github")
    db.add(t)
    db.commit()
    db.refresh(t)
    AuditService.log(db, "token_create", target=t.name, user=user)
    return RedirectResponse(url="/settings?token_ok=1#tokens", status_code=303)

@router.delete("/tokens/{tid}")
def delete_token(tid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    t = db.query(AccessToken).filter(AccessToken.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(t)
    db.commit()
    AuditService.log(db, "token_delete", target=t.name, user=user)
    return {"ok": True}

@router.post("/tokens/{tid}/test")
def test_token(tid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    t = db.query(AccessToken).filter(AccessToken.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="Token not found")
    token_str = str(t.token or "").strip()
    if not token_str:
        return {"ok": False, "login": None, "scopes": [], "error": "Token is empty"}
    try:
        data, scopes = _github_get_with_headers("https://api.github.com/user", token_str)
        scope_list = [s.strip() for s in (scopes or "").split(",") if s.strip()]
        return {"ok": True, "login": data.get("login"), "scopes": scope_list, "error": None}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:500]
        return {"ok": False, "login": None, "scopes": [], "error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"ok": False, "login": None, "scopes": [], "error": str(e)[:500]}

# ---------- Audit ----------

@router.get("/audit", response_model=List[AuditLogOut])
def list_audit(limit: int = 200, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return rows

# ---------- Webhooks ----------

@router.get("/webhooks", response_model=List[WebhookOut])
def list_webhooks(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rows = db.query(Webhook).all()
    return rows

@router.post("/webhooks", response_model=WebhookOut)
def create_webhook(data: WebhookCreate, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    wh = Webhook(**data.model_dump())
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh

@router.delete("/webhooks/{wid}")
def delete_webhook(wid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    wh = db.query(Webhook).filter(Webhook.id == wid).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(wh)
    db.commit()
    return {"ok": True}

@router.post("/webhooks/{wid}/test")
def test_webhook(wid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    wh = db.query(Webhook).filter(Webhook.id == wid).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Not found")
    ok = MonitoringService.send_webhook(wh.url, "test", {"message": "Hello from DockLiner"})
    return {"ok": ok}

# ---------- Notifications ----------

@router.get("/notifications", response_model=List[NotificationOut])
def list_notifications(unread_only: bool = False, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    q = db.query(Notification)
    if unread_only:
        q = q.filter(Notification.read == False)
    return q.order_by(Notification.created_at.desc()).limit(100).all()

@router.post("/notifications/{nid}/read")
def mark_read(nid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    n = db.query(Notification).filter(Notification.id == nid).first()
    if n:
        n.read = True
        db.commit()
    return {"ok": True}

@router.post("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    db.query(Notification).filter(Notification.read == False).update({"read": True}, synchronize_session=False)
    db.commit()
    return {"ok": True}

# ---------- Docker daemon control ----------

@router.post("/docker/start-daemon")
def start_docker_daemon(request: Request, user: str = Depends(require_auth)):
    rc, msg = DockLinerService.start_daemon()
    if rc != 0:
        raise HTTPException(status_code=500, detail=msg)
    return {"ok": True, "message": msg}

@router.post("/docker/stop-daemon")
def stop_docker_daemon(request: Request, user: str = Depends(require_auth)):
    rc, msg = DockLinerService.stop_daemon()
    if rc != 0:
        raise HTTPException(status_code=500, detail=msg)
    return {"ok": True, "message": msg}

# ---------- Backup ----------

@router.get("/docker/info")
def docker_info(user: str = Depends(require_auth)):
    return {
        "installed": DockLinerService.docker_installed(),
        "running": DockLinerService.docker_running(),
        "version": DockLinerService.docker_version(),
    }

@router.get("/docker/stats")
def docker_stats(user: str = Depends(require_auth)):
    return DockLinerService.container_stats()

@router.get("/backup")
def backup(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    buf = io.BytesIO()
    zf = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    db_path = settings.DB_PATH
    if os.path.exists(db_path):
        zf.write(db_path, os.path.basename(db_path))
    for root, dirs, files in os.walk(settings.PROJECTS_DIR):
        for f in files:
            if f == ".env":
                full = os.path.join(root, f)
                arc = os.path.relpath(full, settings.PROJECTS_DIR)
                zf.write(full, arc)
    zf.close()
    buf.seek(0)
    AuditService.log(db, "backup", user=user)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": "attachment; filename=dockliner-backup.zip"})

# ---------- System / Docker info ----------

@router.get("/docker/info")
def docker_info(user: str = Depends(require_auth)):
    return {
        "installed": DockLinerService.docker_installed(),
        "running": DockLinerService.docker_running(),
        "version": DockLinerService.docker_version(),
    }

@router.get("/docker/stats")
def docker_stats(user: str = Depends(require_auth)):
    return DockLinerService.container_stats()

@router.get("/system/version")
def system_version(user: str = Depends(require_auth)):
    from app.services.version_service import VersionService
    return VersionService.check()

@router.get("/system/config")
def system_config(user: str = Depends(require_auth)):
    env_path = Path(os.environ.get("DOCKLINER_ENV_FILE", ".env"))
    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
    else:
        text = _default_env_text()
    return {"path": str(env_path.resolve()), "content": text, "service": os.environ.get("DOCKLINER_SERVICE", "")}

class ConfigUpdate(BaseModel):
    content: str

@router.post("/system/config")
def update_system_config(data: ConfigUpdate, user: str = Depends(require_auth)):
    env_path = Path(os.environ.get("DOCKLINER_ENV_FILE", ".env"))
    try:
        env_path.write_text(data.content, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not write .env: {e}")
    return {"ok": True, "path": str(env_path.resolve())}

@router.post("/system/restart")
def restart_server(user: str = Depends(require_auth)):
    service = os.environ.get("DOCKLINER_SERVICE", "")
    if service:
        if os.name == "nt":
            # Windows: try sc/netsvc, then fallback to dev restart
            for cmd in (["net", "stop", service], ["net", "start", service]), (["sc", "stop", service], ["sc", "start", service]):
                try:
                    subprocess.run(cmd[0], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                    subprocess.run(cmd[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                    return {"ok": True, "mode": "service", "service": service, "method": cmd[0][0]}
                except Exception:
                    continue
            # If no Windows service command worked, fall through to dev restart
        else:
            try:
                subprocess.Popen(["systemctl", "restart", service], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                return {"ok": True, "mode": "service", "service": service, "method": "systemctl"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"systemctl restart failed: {e}")
    # Fallback: detached self-restart (dev mode)
    root = Path(__file__).resolve().parent.parent.parent
    restart_script = root / "scripts" / "restart.py"
    popen_kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "start_new_session": True}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        subprocess.Popen([sys.executable, str(restart_script), str(os.getpid())], **popen_kwargs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restart spawn failed: {e}")
    return {"ok": True, "mode": "dev", "message": "Restart triggered. Refresh in a few seconds."}

def _default_env_text():
    return """# DockLiner configuration
DOCKLINER_SECRET_KEY=change-me
DOCKLINER_HOST=0.0.0.0
DOCKLINER_PORT=8080
# DOCKLINER_SERVICE=dockliner
# Database
DOCKLINER_DB_TYPE=sqlite
DOCKLINER_DB_PATH=./dockliner.db
"""

# ---------- Database / migrations ----------

@router.get("/system/db-info")
def db_info(user: str = Depends(require_auth)):
    from app.core.db import engine, DATABASE_URL, Base
    from app.services.migration_service import MigrationService
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables.keys())
    url = DATABASE_URL
    if url.startswith("mysql://") or url.startswith("mysql+") or url.startswith("postgresql://") or url.startswith("postgresql+"):
        try:
            from urllib.parse import urlparse, urlunparse
            u = urlparse(url)
            if u.password:
                url = urlunparse(u._replace(netloc=u.netloc.replace(u.password, "***")))
        except Exception:
            pass
    info = {
        "url": url,
        "dialect": engine.dialect.name,
        "existing_tables": sorted(existing),
        "model_tables": sorted(model_tables),
        "missing_tables": sorted(model_tables - existing),
        "orphan_tables": sorted(existing - model_tables),
    }
    try:
        info["diff"] = MigrationService.diff_schema(Base)
    except Exception as e:
        info["diff_error"] = str(e)
    counts = {}
    from sqlalchemy.orm import Session as _Session
    with _Session(bind=engine) as session:
        for t in sorted(existing):
            try:
                counts[t] = session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            except Exception as e:
                counts[t] = None
                print(f"[db-info] count failed for {t}: {e}")
    info["row_counts"] = counts
    return info

@router.get("/system/migrations")
def migrations_list(user: str = Depends(require_auth)):
    from app.core.db import Base
    from app.services.migration_service import MigrationService
    return {"operations": MigrationService.diff_schema(Base)}

@router.post("/system/migrations")
def migrations_apply(user: str = Depends(require_auth)):
    from app.core.db import Base
    from app.services.migration_service import MigrationService
    ops = MigrationService.diff_schema(Base)
    if not ops:
        return {"applied": 0, "message": "No migrations needed"}
    result = MigrationService.run_ops(ops)
    return {"applied": result["applied"], "message": f"Applied {result['applied']} migration operations"}

# ---------- Error logs ----------

class JsErrorBody(BaseModel):
    message: str
    stack: Optional[str] = ""
    url: Optional[str] = None
    level: Optional[str] = "error"

@router.post("/error-log")
def log_js_error(data: JsErrorBody, request: Request, db: Session = Depends(get_db)):
    # Do NOT require_auth here; endpoint is hit by frontend error reporter before/after auth.
    # We still accept a user cookie if present.
    user = get_session_user(request)
    ErrorLogService.log(
        db,
        source="js",
        message=data.message,
        level=data.level or "error",
        stack=data.stack or "",
        url=data.url,
        user=user,
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    return {"ok": True}

@router.get("/error-logs")
def list_error_logs(source: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return ErrorLogService.list(db, limit=limit, source=source)


# ---------- Local directory browser ----------

from pathlib import Path as _Path

@router.get("/system/browse")
def browse_local_dir(path: Optional[str] = None, user: str = Depends(require_auth)):
    """Return a safe listing of directories under the given local path."""
    base = _Path(path).expanduser().resolve() if path else _Path.home()
    if not base.exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    if not base.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    try:
        parent = str(base.parent) if base.parent != base else None
        items = []
        for child in sorted(base.iterdir()):
            if child.is_dir() and not child.name.startswith('.'):
                items.append({"name": child.name, "path": str(child), "type": "dir"})
        return {"current": str(base), "parent": parent, "items": items}
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

# ---------- Open error API (rescue even when server startup fails) ----------

import hashlib
from datetime import date

def _today_error_token() -> str:
    if settings.ERROR_API_TOKEN:
        return settings.ERROR_API_TOKEN
    return hashlib.md5(f"{date.today().isoformat()}{settings.SECRET_KEY}".encode()).hexdigest()

async def _open_error_api_auth(request: Request):
    token = request.query_params.get("token")
    if not token:
        try:
            payload = await request.json()
            token = payload.get("token") if isinstance(payload, dict) else None
        except Exception:
            try:
                form = await request.form()
                token = form.get("token")
            except Exception:
                token = None
    if not token or token != _today_error_token():
        raise HTTPException(status_code=401, detail="invalid token")

@router.get("/errors")
async def open_get_errors(request: Request, limit: int = 100, source: Optional[str] = None, db: Session = Depends(get_db)):
    await _open_error_api_auth(request)
    return ErrorLogService.list(db, limit=limit, source=source)

@router.post("/errors")
async def open_post_error(request: Request, db: Session = Depends(get_db)):
    await _open_error_api_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    ErrorLogService.log(
        db,
        source=str(payload.get("source", "external"))[:64],
        message=str(payload.get("message", ""))[:4000],
        level=str(payload.get("level", "error"))[:16],
        stack=str(payload.get("stack", ""))[:8000],
        url=str(payload.get("url", ""))[:500],
        user=str(payload.get("user", ""))[:100],
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    return {"ok": True}

# ---------- Poll trigger ----------

@router.post("/system/poll")
def system_poll(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    MonitoringService.poll_all_health(db)
    MonitoringService.record_docker_stats(db)
    return {"ok": True}

# ---------- Logs ----------

class LogsQuery(BaseModel):
    source: Optional[str] = None
    limit_days: int = 30

@router.get("/logs")
def list_logs(source: Optional[str] = None, limit_days: int = 30, user: str = Depends(require_auth)):
    groups = LogService.grouped_by_day(limit_days=limit_days, source=source)
    return {"groups": groups}

@router.delete("/logs")
def clear_logs(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    db.query(SystemLog).delete()
    db.commit()
    AuditService.log(db, "system_logs_clear", target="system_logs", user=user)
    return {"ok": True}

# ---------- Migrations ----------

from app.services.migration_service import MigrationService
from app.core.db import Base

@router.get("/migrations")
def list_migrations(user: str = Depends(require_auth)):
    ops = MigrationService.diff_schema(Base)
    high = [o for o in ops if o["risk"] == "high"]
    return {"pending": len(ops), "high_risk": len(high), "ops": ops}

class MigrationRunBody(BaseModel):
    sql: List[str] = []

@router.post("/migrations/run")
def run_migrations(body: MigrationRunBody, user: str = Depends(require_auth)):
    if not body.sql:
        raise HTTPException(status_code=400, detail="No SQL provided")
    ops = MigrationService.diff_schema(Base)
    allowed = {o["sql"] for o in ops}
    for sql in body.sql:
        if sql not in allowed:
            raise HTTPException(status_code=400, detail="SQL does not match pending migration")
    result = MigrationService.run_ops([{"sql": s} for s in body.sql])
    return result

# ---------- Docker explorer ----------

from app.services.docker_service import DockerService

@router.get("/docker/containers")
def docker_containers(user: str = Depends(require_auth)):
    return {"containers": DockerService.list_containers()}

@router.get("/docker/images")
def docker_images(user: str = Depends(require_auth)):
    return {"images": DockerService.list_images()}

@router.get("/docker/containers/{container_id}/logs")
def docker_container_logs(container_id: str, tail: int = 200, user: str = Depends(require_auth)):
    return {"logs": DockerService.container_logs_by_project(container_id, tail=tail)}

@router.post("/docker/containers/{container_id}/stop")
def docker_stop_container(container_id: str, user: str = Depends(require_auth)):
    rc, out = DockerService.stop_container(container_id)
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.delete("/docker/containers/{container_id}")
def docker_remove_container(container_id: str, force: bool = False, user: str = Depends(require_auth)):
    rc, out = DockerService.remove_container(container_id, force=force)
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.delete("/docker/images/{image_id}")
def docker_remove_image(image_id: str, force: bool = False, user: str = Depends(require_auth)):
    rc, out = DockerService.remove_image(image_id, force=force)
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}
