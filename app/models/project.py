import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey, Boolean, Enum
import enum
from app.core.db import Base

class DeployMethod(str, enum.Enum):
    compose = "compose"
    build = "build"

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    github_repo_url = Column(String, nullable=True)
    branch = Column(String, nullable=True)
    deploy_path = Column(String, nullable=False)
    compose_file = Column(String, default="docker-compose.yml")
    status = Column(String, default="idle")
    last_deployed = Column(DateTime, nullable=True)
    env_vars = Column(JSON, default=dict)
    env_content = Column(Text, default="")
    example_env_content = Column(Text, default="")
    dockerfile_content = Column(Text, default="")
    compose_content = Column(Text, default="")
    labels = Column(String, default="")
    token_id = Column(Integer, ForeignKey("access_tokens.id"), nullable=True)
    port = Column(Integer, nullable=True)
    deploy_method = Column(String, default="compose")
    release_tag = Column(String, nullable=True)
    command_mode = Column(String, default="compose")  # compose|dockerfile|direct
    raw_mode = Column(Boolean, default=False)
    direct_command = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Deployment(Base):
    __tablename__ = "deployments"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, default="started")  # started/success/error
    logs = Column(Text, default="")

class AccessToken(Base):
    __tablename__ = "access_tokens"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    token = Column(String, nullable=False)
    provider = Column(String, default="github")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class GithubCache(Base):
    __tablename__ = "github_cache"
    id = Column(Integer, primary_key=True, index=True)
    token_id = Column(Integer, ForeignKey("access_tokens.id"), nullable=False)
    endpoint = Column(String, nullable=False)
    payload_json = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class SavedOrg(Base):
    __tablename__ = "saved_orgs"
    id = Column(Integer, primary_key=True, index=True)
    token_id = Column(Integer, ForeignKey("access_tokens.id"), nullable=False)
    org_login = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    saved_at = Column(DateTime, default=datetime.datetime.utcnow)

class Download(Base):
    __tablename__ = "downloads"
    id = Column(Integer, primary_key=True, index=True)
    token_id = Column(Integer, ForeignKey("access_tokens.id"), nullable=False)
    owner = Column(String, nullable=False)
    repo = Column(String, nullable=False)
    ref = Column(String, nullable=False)
    status = Column(String, default="pending")
    download_path = Column(String, nullable=True)
    extracted_path = Column(String, nullable=True)
    size_bytes = Column(Integer, default=0)
    total_bytes = Column(Integer, nullable=True)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if getattr(self, 'size_bytes', None) is None:
            self.size_bytes = 0

class HealthCheck(Base):
    __tablename__ = "health_checks"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    enabled = Column(Boolean, default=False)
    protocol = Column(String, default="http")
    host = Column(String, default="localhost")
    port = Column(Integer, nullable=True)
    path = Column(String, default="/")
    interval_seconds = Column(Integer, default=60)
    last_check = Column(DateTime, nullable=True)
    last_status = Column(String, default="unknown")
    last_latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Metric(Base):
    __tablename__ = "metrics"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    container_id = Column(String, nullable=True)
    container_name = Column(String, nullable=True)
    metric_type = Column(String, nullable=False)
    value = Column(String, nullable=False)
    recorded_at = Column(DateTime, default=datetime.datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user = Column(String, nullable=True)
    action = Column(String, nullable=False)
    target = Column(String, nullable=True)
    ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    details = Column(Text, default="")

class Webhook(Base):
    __tablename__ = "webhooks"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    events = Column(String, default="deploy,health_fail")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    level = Column(String, default="info")
    title = Column(String, nullable=False)
    body = Column(Text, default="")
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class ErrorLog(Base):
    __tablename__ = "error_logs"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False)  # python|js
    level = Column(String, default="error")  # error|warn|info
    message = Column(Text, default="")
    stack = Column(Text, default="")
    url = Column(String, nullable=True)
    user = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
