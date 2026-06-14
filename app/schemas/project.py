from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from datetime import datetime

class ProjectCreate(BaseModel):
    name: str
    github_repo_url: Optional[str] = None
    branch: str = "main"
    compose_file: str = "docker-compose.yml"
    env_vars: Optional[Dict[str, Any]] = None
    labels: Optional[str] = ""
    is_our_hosted: bool = False
    blue_port: Optional[int] = None
    green_port: Optional[int] = None

class ProjectUpdate(BaseModel):
    github_repo_url: Optional[str] = None
    branch: Optional[str] = None
    compose_file: Optional[str] = None
    env_vars: Optional[Dict[str, Any]] = None
    labels: Optional[str] = None
    is_our_hosted: Optional[bool] = None
    blue_port: Optional[int] = None
    green_port: Optional[int] = None

class ProjectOut(BaseModel):
    id: int
    name: str
    github_repo_url: Optional[str]
    branch: str
    deploy_path: str
    compose_file: str
    status: str
    last_deployed: Optional[datetime]
    env_vars: Optional[Dict[str, Any]]
    labels: Optional[str]
    is_our_hosted: bool
    active_slot: str
    blue_port: Optional[int]
    green_port: Optional[int]
    created_at: datetime
    class Config:
        from_attributes = True

class DeploymentOut(BaseModel):
    id: int
    project_id: int
    timestamp: datetime
    status: str
    logs: str
    slot: Optional[str]
    class Config:
        from_attributes = True

class AccessTokenCreate(BaseModel):
    name: str
    token: str
    provider: str = "github"

class AccessTokenOut(BaseModel):
    id: int
    name: str
    provider: str
    created_at: datetime
    class Config:
        from_attributes = True

class DockerHostCreate(BaseModel):
    name: str
    host: str = "localhost"
    is_local: bool = True
    tls: bool = False

class DockerHostOut(BaseModel):
    id: int
    name: str
    host: str
    is_local: bool
    tls: bool
    created_at: datetime
    class Config:
        from_attributes = True