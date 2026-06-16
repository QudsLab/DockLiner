from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.auth import require_auth
from app.models.project import Project, Deployment, AccessToken
from app.services.docker_service import DockerService
from pathlib import Path
import json

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request})

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    projects = db.query(Project).all()
    containers = DockerService.list_containers()
    images = DockerService.list_images()
    tokens = db.query(AccessToken).all()
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request, "projects": projects, "containers": containers,
        "images": images, "tokens": tokens,
    })

@router.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    items = db.query(Project).all()
    tokens = db.query(AccessToken).all()
    return templates.TemplateResponse(request, "projects.html", {"request": request, "projects": items, "tokens": tokens})

@router.get("/projects/add", response_class=HTMLResponse)
def projects_add_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    tokens = db.query(AccessToken).all()
    return templates.TemplateResponse(request, "project_add.html", {"request": request, "tokens": tokens})

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    tokens = db.query(AccessToken).all()
    containers = DockerService.list_containers()
    images = DockerService.list_images()
    networks = DockerService.list_networks()
    volumes = DockerService.list_volumes()
    info = DockerService.docker_info()
    sec = DockerService.security_summary()
    # Read version from VERSION file
    version = {"current": "dev", "latest": "unknown", "has_update": False}
    vf = Path(__file__).resolve().parents[2] / "VERSION"
    if vf.exists():
        version["current"] = vf.read_text().strip()
    return templates.TemplateResponse(request, "settings.html", {
        "request": request, "tokens": tokens,
        "containers": containers, "images": images,
        "networks": networks, "volumes": volumes,
        "info": info, "sec": sec, "version": version,
        "docker_installed": DockerService.is_installed(),
        "docker_running": DockerService.is_running(),
        "docker_version": DockerService.installed_version(),
    })

@router.get("/projects/{pid}/logs", response_class=HTMLResponse)
def logs_page(request: Request, pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    logs = ""
    if p:
        from app.services.deploy_service import DeployService
        logs = DeployService.project_logs(p, 200)
    return templates.TemplateResponse(request, "logs.html", {"request": request, "project": p, "logs": logs})

@router.get("/logout", response_class=HTMLResponse)
def logout_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request})
