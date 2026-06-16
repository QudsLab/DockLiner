from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from pathlib import Path
import io, zipfile, json, os, urllib.request, urllib.error
from app.core.db import get_db
from app.core.config import settings
from app.core.auth import verify, login_user, logout_user, get_session_user, require_auth
from app.core.utils import find_free_ports
from app.models.project import (
    Project, Deployment, AccessToken, GithubCache, SavedOrg, Download,
    HealthCheck, Metric, AuditLog, Webhook, Notification
)
from app.models.project import (
    Project, Deployment, AccessToken, GithubCache, SavedOrg, Download,
    HealthCheck, Metric, AuditLog, Webhook, Notification, ErrorLog
)
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectOut,
    DeploymentOut, AccessTokenCreate, AccessTokenOut,
)
from app.schemas.monitoring import (
    HealthCheckCreate, HealthCheckUpdate, HealthCheckOut,
    MetricOut, AuditLogOut, WebhookCreate, WebhookOut, NotificationOut,
)
from app.services.deploy_service import DeployService
from app.services.docker_service import DockerService
from app.services.github_download_service import GitHubDownloadService
from app.services.monitoring_service import MonitoringService, AuditService, RateLimitService
from app.services.file_scanner import scan_downloaded_repo
from app.services.error_log_service import ErrorLogService
import yaml, urllib.parse, shutil

router = APIRouter(prefix="/api", tags=["api"])

class LoginBody(BaseModel):
    user: str
    pass_: str = Field(..., alias="pass")

@router.post("/login")
def api_login(data: LoginBody, response: Response, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else ""
    if not RateLimitService.limit_login(ip):
        AuditService.log(db, "login_denied", target=data.user, details="rate limited", ip=ip, user_agent=request.headers.get("user-agent",""))
        raise HTTPException(status_code=429, detail="Too many login attempts")
    if verify(data.user, data.pass_):
        for k, v in login_user(data.user).items():
            response.set_cookie(k, v, httponly=True, samesite="lax")
        AuditService.log(db, "login", target=data.user, details="success", user=data.user, ip=ip, user_agent=request.headers.get("user-agent",""))
        return {"ok": True}
    AuditService.log(db, "login_failed", target=data.user, details="bad password", ip=ip, user_agent=request.headers.get("user-agent",""))
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
    existing = db.query(Project).filter(Project.name == data.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Project name exists")
    deploy_path = str(Path(settings.PROJECTS_DIR) / data.name)
    port = data.port
    if port is None:
        free = find_free_ports(25600, 1)
        port = free[0] if free else 25600
    p = Project(
        name=data.name,
        github_repo_url=data.github_repo_url,
        branch=data.branch or "main",
        deploy_path=deploy_path,
        compose_file=data.compose_file or "docker-compose.yml",
        env_vars=data.env_vars or {},
        env_content=data.env_content or "",
        example_env_content=data.example_env_content or "",
        dockerfile_content=data.dockerfile_content or "",
        compose_content=data.compose_content or "",
        labels=data.labels or "",
        token_id=data.token_id,
        port=port,
        deploy_method=data.deploy_method or "compose",
        release_tag=data.release_tag,
        command_mode=data.command_mode or "compose",
        raw_mode=data.raw_mode or False,
        direct_command=data.direct_command or "",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    # Persist files
    ppath = Path(str(p.deploy_path))
    ppath.mkdir(parents=True, exist_ok=True)
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
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    AuditService.log(db, "project_update", target=p.name, user=user)
    return p

@router.delete("/projects/{pid}")
def delete_project(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
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
    dep = DeployService.deploy_project(p, tok.token if tok else None, db)
    return {'deployment_id': dep.id, 'status': dep.status}

@router.post("/projects/{pid}/start")
def start_project(pid: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    out = DeployService.start_project(p)
    db.commit()
    AuditService.log(db, "start", target=p.name, user=user, ip=request.client.host if request.client else "")
    return {"status": p.status, "output": out}

@router.post("/projects/{pid}/stop")
def stop_project(pid: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    out = DeployService.stop_project(p)
    db.commit()
    AuditService.log(db, "stop", target=p.name, user=user, ip=request.client.host if request.client else "")
    return {"status": p.status, "output": out}

@router.post("/projects/{pid}/restart")
def restart_project(pid: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    out = DeployService.restart_project(p)
    db.commit()
    AuditService.log(db, "restart", target=p.name, user=user, ip=request.client.host if request.client else "")
    return {"status": p.status, "output": out}

@router.get("/projects/{pid}/logs")
def project_logs(pid: int, tail: int = 200, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return {"logs": DeployService.project_logs(p, tail)}

@router.get("/projects/{pid}/deployments", response_model=List[DeploymentOut])
def list_deployments(pid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return db.query(Deployment).filter(Deployment.project_id == pid).order_by(Deployment.timestamp.desc()).all()

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
    return DockerService.list_containers()

@router.get("/docker/images")
def list_images(user: str = Depends(require_auth)):
    return DockerService.list_images()

@router.get("/docker/networks")
def list_networks(user: str = Depends(require_auth)):
    return DockerService.list_networks()

@router.get("/docker/volumes")
def list_volumes(user: str = Depends(require_auth)):
    return DockerService.list_volumes()

@router.get("/docker/security")
def docker_security(user: str = Depends(require_auth)):
    return DockerService.security_summary()

@router.post("/docker/containers/{cid}/stop")
def stop_container(cid: str, request: Request, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rc, out = DockerService.stop_container(cid)
    AuditService.log(db, "container_stop", target=cid, user=user, ip=request.client.host if request.client else "")
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.post("/docker/containers/{cid}/remove")
def remove_container(cid: str, request: Request, force: bool = False, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rc, out = DockerService.remove_container(cid, force)
    AuditService.log(db, "container_remove", target=cid, user=user, ip=request.client.host if request.client else "")
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.post("/docker/images/{iid}/remove")
def remove_image(iid: str, request: Request, force: bool = False, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rc, out = DockerService.remove_image(iid, force)
    AuditService.log(db, "image_remove", target=iid, user=user, ip=request.client.host if request.client else "")
    if rc != 0:
        raise HTTPException(status_code=500, detail=out)
    return {"ok": True, "output": out}

@router.get("/docker/containers/{cid}/ports")
def container_ports(cid: str, user: str = Depends(require_auth)):
    return DockerService.inspect_container_ports(cid)

@router.get("/docker/containers/{cid}/logs")
def container_logs(cid: str, tail: int = 200, user: str = Depends(require_auth)):
    return {"logs": DockerService.container_logs(cid, tail)}

@router.get("/docker/containers/{cid}/top")
def container_top(cid: str, user: str = Depends(require_auth)):
    return DockerService.container_top(cid)

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
    try:
        GitHubDownloadService.run_download(dl.id, str(tok.token), db)
    except Exception as e:
        db.refresh(dl)
        raise HTTPException(status_code=500, detail=dl.error_message or str(e))
    return GitHubDownloadService.scan(dl)

@router.get("/github/download/{dl_id}")
def github_download_status(dl_id, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    dl = db.query(Download).filter(Download.id == dl_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Download not found")
    return GitHubDownloadService.scan(dl)

@router.get("/github/downloads")
def github_download_list(limit: int = 50, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rows = db.query(Download).order_by(Download.created_at.desc()).limit(limit).all()
    out = []
    for dl in rows:
        out.append({
            "id": dl.id,
            "owner": dl.owner,
            "repo": dl.repo,
            "ref": dl.ref,
            "status": dl.status,
            "size_bytes": dl.size_bytes,
            "total_bytes": dl.total_bytes,
            "created_at": dl.created_at,
            "updated_at": dl.updated_at,
        })
    return out

@router.delete("/github/download/{dl_id}")
def github_download_delete(dl_id, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    dl = db.query(Download).filter(Download.id == dl_id).first()
    if not dl:
        raise HTTPException(status_code=404, detail="Download not found")
    GitHubDownloadService.delete_download(dl, db)
    return {"ok": True}

@router.post("/github/downloads/cleanup")
def github_download_cleanup(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    rows = db.query(Download).all()
    removed = 0
    for dl in rows:
        try:
            GitHubDownloadService.delete_download(dl, db)
            removed += 1
        except Exception:
            pass
    return {"removed": removed}

# ---------- Tokens ----------

@router.get("/tokens", response_model=List[AccessTokenOut])
def list_tokens(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    return db.query(AccessToken).all()

@router.post("/tokens", response_model=AccessTokenOut)
def create_token(data: AccessTokenCreate, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    t = AccessToken(name=data.name, token=data.token, provider=data.provider)
    db.add(t)
    db.commit()
    db.refresh(t)
    AuditService.log(db, "token_create", target=t.name, user=user)
    return t

@router.delete("/tokens/{tid}")
def delete_token(tid: int, db: Session = Depends(get_db), user: str = Depends(require_auth)):
    t = db.query(AccessToken).filter(AccessToken.id == tid).first()
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(t)
    db.commit()
    AuditService.log(db, "token_delete", target=t.name, user=user)
    return {"ok": True}

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
    rc, msg = DockerService.start_daemon()
    if rc != 0:
        raise HTTPException(status_code=500, detail=msg)
    return {"ok": True, "message": msg}

@router.post("/docker/stop-daemon")
def stop_docker_daemon(request: Request, user: str = Depends(require_auth)):
    rc, msg = DockerService.stop_daemon()
    if rc != 0:
        raise HTTPException(status_code=500, detail=msg)
    return {"ok": True, "message": msg}

# ---------- Backup ----------

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
        "installed": DockerService.is_installed(),
        "running": DockerService.is_running(),
        "version": DockerService.installed_version(),
    }

@router.get("/docker/stats")
def docker_stats(user: str = Depends(require_auth)):
    return DockerService.system_stats()

@router.get("/system/version")
def system_version(user: str = Depends(require_auth)):
    from app.services.version_service import VersionService
    return VersionService.check()

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

# ---------- Poll trigger ----------

@router.post("/system/poll")
def system_poll(db: Session = Depends(get_db), user: str = Depends(require_auth)):
    MonitoringService.poll_all_health(db)
    MonitoringService.record_docker_stats(db)
    return {"ok": True}
