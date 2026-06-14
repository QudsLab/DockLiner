from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.models.project import Project, Deployment, AccessToken, DockerHost
from app.services.docker_service import DockerService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).all()
    containers = DockerService.list_containers()
    images = DockerService.list_images()
    tokens = db.query(AccessToken).all()
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "projects": projects,
        "containers": containers,
        "images": images,
        "tokens": tokens,
    })

@router.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db)):
    items = db.query(Project).all()
    return templates.TemplateResponse(request, "projects.html", {"request": request, "projects": items})

@router.get("/docker", response_class=HTMLResponse)
def docker_page(request: Request, db: Session = Depends(get_db)):
    containers = DockerService.list_containers()
    images = DockerService.list_images()
    networks = DockerService.list_networks()
    volumes = DockerService.list_volumes()
    hosts = db.query(DockerHost).all()
    return templates.TemplateResponse(request, "docker.html", {
        "request": request,
        "containers": containers,
        "images": images,
        "networks": networks,
        "volumes": volumes,
        "hosts": hosts,
    })

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    tokens = db.query(AccessToken).all()
    hosts = db.query(DockerHost).all()
    return templates.TemplateResponse(request, "settings.html", {
        "request": request,
        "tokens": tokens,
        "hosts": hosts,
    })

@router.get("/projects/{pid}/logs", response_class=HTMLResponse)
def logs_page(request: Request, pid: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == pid).first()
    logs = ""
    if p:
        slot = p.active_slot or "blue"
        slot_path = p.deploy_path + "/" + slot
        logs = DockerService.compose_logs(slot_path, p.compose_file, 200)
    return templates.TemplateResponse(request, "logs.html", {"request": request, "project": p, "logs": logs})