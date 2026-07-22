from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.auth import require_auth
from app.models.project import Project, Deployment, AccessToken, Download, SystemLog
from app.services.dockliner_service import DockLinerService
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

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    projects = db.query(Project).all()
    containers = DockLinerService.list_containers()
    images = DockLinerService.list_images()
    networks = DockLinerService.list_networks()
    volumes = DockLinerService.list_volumes()
    tokens = db.query(AccessToken).all()
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request, "projects": projects, "containers": containers,
        "images": images, "networks": networks, "volumes": volumes,
        "tokens": tokens,
        "docker_installed": DockLinerService.docker_installed(),
        "docker_running": DockLinerService.docker_running(),
        "docker_version": DockLinerService.docker_version(),
    })

@router.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    from app.services.cleanup_service import CleanupService
    registered = db.query(Project).all()
    scan = CleanupService.scan(db)
    return templates.TemplateResponse(request, "projects.html", {
        "request": request, "projects": registered, "tokens": db.query(AccessToken).all(),
        "orphan_projects": scan["projects"], "orphan_downloads": scan["downloads"],
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
        "source_path": (dl.extracted_path if dl and dl.extracted_path else urllib.parse.unquote(path)) if source in ("download", "local") else "",
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
            lower == ".env" or lower == "env" or lower.endswith("/.env") or lower.endswith("/env")
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
    sec = DockLinerService.security_summary()
    from app.services.version_service import VersionService
    version = VersionService.check()
    return templates.TemplateResponse(request, "settings.html", {
        "request": request, "tokens": tokens,
        "sec": sec, "version": version,
    })

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

@router.get("/projects/{pid}", response_class=HTMLResponse)
def project_detail_page(request: Request, pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    tokens = db.query(AccessToken).all()
    return templates.TemplateResponse(request, "project_detail.html", {"request": request, "project": p, "tokens": tokens})

@router.get("/cleanup", response_class=HTMLResponse)
def cleanup_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return templates.TemplateResponse(request, "cleanup.html", {"request": request})

@router.get("/logout", response_class=HTMLResponse)
def logout_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request})
