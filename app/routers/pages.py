from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.auth import require_auth
from app.models.project import Project, Deployment, AccessToken, Download, SystemLog
from app.services.dockliner_service import DockLinerService
from app.services.docker_service import DockerService
from app.services.project_status_service import ProjectStatusService
from app.services.file_scanner import scan_local_dir
from app.services.log_service import LogService
from pathlib import Path
import json
import urllib.parse

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request})

import socket
import urllib.request

def _get_ips():
    public = None
    private = None
    try:
        with urllib.request.urlopen('https://api.ipify.org?format=json', timeout=5) as r:
            public = json.loads(r.read().decode()).get('ip')
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 53))
        private = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    return {"public": public or "-", "private": private or "-"}

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    projects = db.query(Project).all()
    from app.services.cleanup_service import CleanupService
    scan = CleanupService.scan(db)
    containers = DockLinerService.list_containers()
    images = DockLinerService.list_images()
    running = sum(1 for c in containers if str(c.get('State','')).lower() == 'running')
    offline = len(containers) - running
    ips = _get_ips()
    tokens = db.query(AccessToken).all()
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request, "projects": projects,
        "containers": containers, "images": images,
        "running_count": running, "offline_count": offline,
        "orphan_downloads": scan["downloads"],
        "ips": ips,
        "tokens": tokens,
        "docker_installed": DockLinerService.docker_installed(),
        "docker_running": DockLinerService.docker_running(),
        "docker_version": DockLinerService.docker_version(),
    })

@router.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    from app.services.cleanup_service import CleanupService
    registered = db.query(Project).all()
    for p in registered:
        ProjectStatusService.sync_status(db, p, commit=False)
    db.commit()
    scan = CleanupService.scan(db)
    show_ports = False  # DockLiner no longer stores project ports in DB; ports come from Docker runtime only.
    return templates.TemplateResponse(request, "projects.html", {
        "request": request, "projects": registered, "tokens": db.query(AccessToken).all(),
        "orphan_projects": scan["projects"], "orphan_downloads": scan["downloads"],
        "show_ports": show_ports,
    })

@router.get("/projects/add", response_class=HTMLResponse)
def projects_add_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    tokens = db.query(AccessToken).all()
    return templates.TemplateResponse(request, "project_add.html", {"request": request, "tokens": tokens})

@router.get("/projects/setup", response_class=HTMLResponse)
def projects_setup_page(
    request: Request,
    source: str = "github",
    path: str = "",
    download_id: int = 0,
    db: Session = Depends(get_db),
    user: str = Depends(require_auth),
):
    if source not in ("github", "local", "download"):
        raise HTTPException(status_code=400, detail="Invalid source")

    scan_data = {}
    file_map = {}
    tokens = db.query(AccessToken).all()
    dl = None

    if source == "download":
        dl = db.query(Download).filter(Download.id == download_id).first() if download_id else None
        if not dl or not dl.extracted_path:
            raise HTTPException(status_code=404, detail="Download not ready")
        scan_data = scan_local_dir(dl.extracted_path)
        scan_data["clone_url"] = f"https://github.com/{dl.owner}/{dl.repo}.git"
        file_map = _build_file_map(dl.extracted_path, scan_data.get("files", []))
    elif source == "local":
        decoded_path = urllib.parse.unquote(path)
        if not decoded_path:
            raise HTTPException(status_code=400, detail="Path required")
        if not Path(decoded_path).exists():
            raise HTTPException(status_code=400, detail="Directory does not exist")
        scan_data = scan_local_dir(decoded_path)
        file_map = _build_file_map(decoded_path, scan_data.get("files", []))
    else:
        # github source requires a download_id in this flow too; otherwise just show empty builder
        if download_id:
            dl = db.query(Download).filter(Download.id == download_id).first()
            if dl and dl.extracted_path:
                scan_data = scan_local_dir(dl.extracted_path)
                scan_data["clone_url"] = f"https://github.com/{dl.owner}/{dl.repo}.git"
                file_map = _build_file_map(dl.extracted_path, scan_data.get("files", []))

    scan_data["file_map"] = file_map

    return templates.TemplateResponse(request, "project_setup.html", {
        "request": request,
        "source": source,
        "path": urllib.parse.unquote(path),
        "download_id": download_id,
        "source_path": (dl.extracted_path if dl and dl.extracted_path else urllib.parse.unquote(path)) if source in ("github", "download", "local") else "",
        "scan_json": json.dumps(scan_data),
        "tokens": tokens,
    })


def _build_file_map(root: str, files: list) -> dict:
    """Read contents for likely compose/Dockerfile/env candidates so the setup picker can switch between them."""
    root_path = Path(root)
    map_data = {}
    for f in files:
        lower = f.lower()
        is_candidate = (
            lower.endswith("compose.yml") or lower.endswith("compose.yaml") or
            lower.endswith("docker-compose.yml") or lower.endswith("docker-compose.yaml") or
            lower == "dockerfile" or lower.endswith("/dockerfile") or
            lower == ".env" or lower == "env" or lower.endswith("/.env") or lower.endswith("/env") or
            lower == ".env.example" or lower.endswith("/.env.example") or
            lower == ".env.sample" or lower.endswith("/.env.sample") or
            lower == ".env.template" or lower.endswith("/.env.template")
        )
        if not is_candidate:
            continue
        try:
            target = (root_path / f).resolve()
            if not str(target).startswith(str(root_path.resolve())):
                continue
            # Use relative path as key so the picker matches scan data keys.
            try:
                key = str(target.relative_to(root_path.resolve()))
            except Exception:
                key = f
            map_data[key] = target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
    return map_data

@router.get("/downloads", response_class=HTMLResponse)
def downloads_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    items = DockLinerService.list_downloads(db)
    return templates.TemplateResponse(request, "downloads.html", {"request": request, "downloads": items})

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    tokens = db.query(AccessToken).all()
    sec = {"containers_checked": 0, "issues": [], "score": 100}
    version = {"current": "", "latest": "", "has_update": False, "url": None}
    return templates.TemplateResponse(request, "settings.html", {
        "request": request, "tokens": tokens,
        "sec": sec, "version": version,
    })

@router.get("/settings/database", response_class=HTMLResponse)
def settings_database_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    from app.core.db import Base
    from app.services.migration_service import MigrationService
    return templates.TemplateResponse(request, "settings_database.html", {
        "request": request,
        "db_url": "",  # fetched client-side via API
        "operations": MigrationService.diff_schema(Base),
    })

@router.get("/settings/config", response_class=HTMLResponse)
def settings_config_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return templates.TemplateResponse(request, "settings_config.html", {"request": request})

@router.get("/projects/{pid}/logs", response_class=HTMLResponse)
def logs_page(request: Request, pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    logs = ""
    if p:
        from app.services.deploy_service import DeployService
        logs = DeployService.project_logs(p, 200)
    return templates.TemplateResponse(request, "logs.html", {"request": request, "project": p, "logs": logs})

@router.get("/logs", response_class=HTMLResponse)
def system_logs_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    groups = LogService.grouped_by_day(limit_days=30)
    return templates.TemplateResponse(request, "system_logs.html", {"request": request, "groups": groups})

@router.get("/hub", response_class=HTMLResponse)
def hub_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    containers = []
    images = []
    docker_version = ""
    docker_running = False
    try:
        containers = DockerService.list_containers()
        images = DockerService.list_images()
        docker_version = DockerService.installed_version()
        docker_running = DockerService.is_running()
    except Exception:
        pass
    return templates.TemplateResponse(request, "hub.html", {
        "request": request, "containers": containers, "images": images,
        "docker_installed": DockerService.is_installed(),
        "docker_running": docker_running,
        "docker_version": docker_version,
    })

@router.get("/projects/{pid}", response_class=HTMLResponse)
def project_detail_page(request: Request, pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    statuses = ProjectStatusService.sync_status(db, p, commit=True)
    tokens = db.query(AccessToken).all()
    files_changed = ProjectStatusService.files_changed_since_deploy(p)
    return templates.TemplateResponse(request, "project_detail.html", {
        "request": request,
        "project": p,
        "tokens": tokens,
        "container_status": statuses["container_status"],
        "build_status": statuses["build_status"],
        "files_changed": files_changed,
    })

@router.get("/projects/{pid}/editor", response_class=HTMLResponse)
def project_editor_page(request: Request, pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(request, "project_editor.html", {"request": request, "project": p})
@router.get("/cleanup", response_class=HTMLResponse)
def cleanup_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return templates.TemplateResponse(request, "cleanup.html", {"request": request})

@router.get("/logout", response_class=HTMLResponse)
def logout_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request})

@router.get("/migration", response_class=HTMLResponse)
def migration_page(request: Request):
    from app.core.db import PENDING_MIGRATION_OPS
    return templates.TemplateResponse(request, "migration.html", {
        "request": request,
        "ops": PENDING_MIGRATION_OPS,
        "count": len(PENDING_MIGRATION_OPS),
    })