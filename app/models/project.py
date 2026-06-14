import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey, Boolean
from app.core.db import Base

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    github_repo_url = Column(String, nullable=True)
    branch = Column(String, default="main")
    deploy_path = Column(String, nullable=False)
    compose_file = Column(String, default="docker-compose.yml")
    status = Column(String, default="idle")  # idle/running/stopped/error/deploying
    last_deployed = Column(DateTime, nullable=True)
    env_vars = Column(JSON, default=dict)
    labels = Column(String, default="")
    is_our_hosted = Column(Boolean, default=False)
    # Blue-green fields
    active_slot = Column(String, default="blue")  # blue or green
    blue_path = Column(String, nullable=True)
    green_path = Column(String, nullable=True)
    blue_port = Column(Integer, nullable=True)
    green_port = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Deployment(Base):
    __tablename__ = "deployments"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, default="started")  # started/success/error
    logs = Column(Text, default="")
    slot = Column(String, nullable=True)

class AccessToken(Base):
    __tablename__ = "access_tokens"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    token = Column(String, nullable=False)
    provider = Column(String, default="github")  # github / gitlab / generic
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class DockerHost(Base):
    __tablename__ = "docker_hosts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    host = Column(String, default="localhost")
    is_local = Column(Boolean, default=True)
    tls = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)