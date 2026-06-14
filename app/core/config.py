import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_PATH: str = "./dockliner.db"
    PROJECTS_DIR: str = "./projects"
    GITHUB_CACHE: str = "./github-cache"
    LOGS_DIR: str = "./logs"
    SECRET_KEY: str = "change-me"
    ADMIN_USER: str = "admin"
    ADMIN_PASS: str = "admin"
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    MAX_ACCESS_TOKENS: int = 10
    class Config:
        env_file = ".env"
        env_prefix = "DOCKLINER_"
        extra = "ignore"

settings = Settings()

# Ensure dirs exist
Path(settings.PROJECTS_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.GITHUB_CACHE).mkdir(parents=True, exist_ok=True)
Path(settings.LOGS_DIR).mkdir(parents=True, exist_ok=True)