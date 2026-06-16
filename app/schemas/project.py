from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from datetime import datetime

class ProjectCreate(BaseModel):
    name: str
    github_repo_url: Optional[str] = None
    branch: Optional[str] = "main"
    compose_file: str = "docker-compose.yml"
    env_vars: Optional[Dict[str, Any]] = None
    env_content: Optional[str] = None
    example_env_content: Optional[str] = None
    dockerfile_content: Optional[str] = None
    compose_content: Optional[str] = None
    labels: Optional[str] = ""
    token_id: Optional[int] = None
    port: Optional[int] = None
    deploy_method: Optional[str] = "compose"
    release_tag: Optional[str] = None
    command_mode: Optional[str] = "compose"  # compose|dockerfile|direct
    raw_mode: Optional[bool] = False

class ProjectUpdate(BaseModel):
    github_repo_url: Optional[str] = None
    branch: Optional[str] = None
    compose_file: Optional[str] = None
    env_vars: Optional[Dict[str, Any]] = None
    env_content: Optional[str] = None
    example_env_content: Optional[str] = None
    dockerfile_content: Optional[str] = None
    compose_content: Optional[str] = None
    labels: Optional[str] = None
    token_id: Optional[int] = None
    port: Optional[int] = None
    deploy_method: Optional[str] = None
    release_tag: Optional[str] = None
    command_mode: Optional[str] = None
    raw_mode: Optional[bool] = None

class ProjectOut(BaseModel):
    id: int
    name: str
    github_repo_url: Optional[str]
    branch: Optional[str]
    deploy_path: str
    compose_file: str
    status: str
    last_deployed: Optional[datetime]
    env_vars: Optional[Dict[str, Any]]
    labels: Optional[str]
    token_id: Optional[int]
    port: Optional[int]
    deploy_method: Optional[str]
    release_tag: Optional[str]
    created_at: datetime
    class Config:
        from_attributes = True

class DeploymentOut(BaseModel):
    id: int
    project_id: int
    timestamp: datetime
    status: str
    logs: str
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
