from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pathlib import Path
from app.core.db import get_db
from app.core.config import settings
from app.models.project import Project, Deployment, AccessToken, DockerHost
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectOut,
    DeploymentOut, AccessTokenCreate, AccessTokenOut,
    DockerHostCreate, DockerHostOut,
)
from app.services.deploy_service import DeployService
from app.services.docker_service import DockerService

router = APIRouter(prefix="/api", tags=["api"])

@router.get("/projects", response_model=List[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).all()

@router.post("/projects", response_model=ProjectOut)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.query(Project).filter(Project.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Project name exists")
    deploy_path = str(Path(settings.PROJECTS_DIR) / data.name)
    p = Project(
        name=data.name,
        github_repo_url=data.github_repo_url,
        branch=data.branch or "main",
        deploy_path=deploy_path,
        compose_file=data.compose_file or "docker-compose.yml",
        env_vars=data.env_vars or {},
        labels=data.labels or "",
        is_our_hosted=data.is_our_hosted,
        blue_port=data.blue_port,
        green_port=data.green_port,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p

@router.get("/projects/{pid}", response_model=ProjectOut)
def get_project(pid: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return p

@router.patch("/projects/{pid}", response_model=ProjectOut)
def update_project(pid: int, data: ProjectUpdate, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p

@router.delete("/projects/{pid}")
def delete_project(pid: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    db.query(Deployment).filter(Deployment.project_id == pid).delete()
    db.delete(p)
    db.commit()
    return {"ok": True}

@router.post("/projects/{pid}/deploy")
def deploy_project(pid: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    tok = db.query(AccessToken).first()
    dep = DeployService.deploy_project(p, tok.token if tok else None, db)
    return {"deployment_id": dep.id, "status": dep.status}

@router.post("/projects/{pid}/stop")
def stop_project(pid: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    out = DeployService.stop_project(p)
    db.commit()
    return {"status": p.status, "output": out}

@router.post("/projects/{pid}/restart")
def restart_project(pid: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    out = DeployService.restart_project(p)
    db.commit()
    return {"status": p.status, "output": out}

@router.get("/projects/{pid}/logs")
def project_logs(pid: int, tail: int = 100, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    slot = p.active_slot or "blue"
    slot_path = Path(p.deploy_path) / slot
    return {"logs": DockerService.compose_logs(str(slot_path), p.compose_file, tail)}

@router.get("/projects/{pid}/deployments", response_model=List[DeploymentOut])
def list_deployments(pid: int, db: Session = Depends(get_db)):
    return db.query(Deployment).filter(Deployment.project_id == pid).order_by(Deployment.timestamp.desc()).all()

@router.get("/docker/containers")
def list_containers():
    return DockerService.list_containers()

@router.get("/docker/images")
def list_images():
    return DockerService.list_images()

@router.get("/docker/networks")
def list_networks():
    return DockerService.list_networks()

@router.get("/docker/volumes")
def list_volumes():
    return DockerService.list_volumes()

@router.post("/docker/containers/{cid}/stop")
def stop_container(cid: str):
    rc, out = DockerService.stop_container(cid)
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.post("/docker/containers/{cid}/remove")
def remove_container(cid: str, force: bool = False):
    rc, out = DockerService.remove_container(cid, force)
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.post("/docker/images/{iid}/remove")
def remove_image(iid: str, force: bool = False):
    rc, out = DockerService.remove_image(iid, force)
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.get("/docker/containers/{cid}/ports")
def container_ports(cid: str):
    return DockerService.inspect_container_ports(cid)

@router.get("/tokens", response_model=List[AccessTokenOut])
def list_tokens(db: Session = Depends(get_db)):
    return db.query(AccessToken).all()

@router.post("/tokens", response_model=AccessTokenOut)
def create_token(data: AccessTokenCreate, db: Session = Depends(get_db)):
    t = AccessToken(name=data.name, token=data.token, provider=data.provider)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t

@router.delete("/tokens/{tid}")
def delete_token(tid: int, db: Session = Depends(get_db)):
    t = db.query(AccessToken).filter(AccessToken.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(t)
    db.commit()
    return {"ok": True}

@router.get("/docker-hosts", response_model=List[DockerHostOut])
def list_hosts(db: Session = Depends(get_db)):
    return db.query(DockerHost).all()

@router.post("/docker-hosts", response_model=DockerHostOut)
def create_host(data: DockerHostCreate, db: Session = Depends(get_db)):
    h = DockerHost(name=data.name, host=data.host, is_local=data.is_local, tls=data.tls)
    db.add(h)
    db.commit()
    db.refresh(h)
    return h

@router.delete("/docker-hosts/{hid}")
def delete_host(hid: int, db: Session = Depends(get_db)):
    h = db.query(DockerHost).filter(DockerHost.id == hid).first()
    if not h:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(h)
    db.commit()
    return {"ok": True}
