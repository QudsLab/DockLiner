import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database: either set DATABASE_URL directly, or use DB_TYPE + DB_* variables.
    # Examples:
    #   DATABASE_URL=sqlite:///./dockliner.db
    #   DATABASE_URL=mysql+pymysql://user:***@localhost/dockliner
    #   DATABASE_URL=postgresql+psycopg2://user:pass@localhost/dockliner
    DATABASE_URL: Optional[str] = None
    DB_TYPE: str = "sqlite"              # sqlite | mysql | postgres
    DB_DRIVER: str = "pymysql"           # pymysql (mysql) or psycopg2 (postgres)
    DB_HOST: str = "localhost"
    DB_PORT: Optional[int] = None
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_NAME: str = "dockliner"

    DB_PATH: str = "./dockliner.db"     # legacy fallback for sqlite

    PROJECTS_DIR: str = "./projects"
    DOWNLOADS_DIR: str = "./downloads"
    LOGS_DIR: str = "./logs"
    SECRET_KEY: str = "change-me"
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    MAX_ACCESS_TOKENS: int = 10
    DOCKER_EXECUTABLE: Optional[str] = None
    # Token for the open error API. If not set, falls back to md5(YYYY-MM-DD + SECRET_KEY).
    ERROR_API_TOKEN: Optional[str] = None
    # Default users as JSON array of {"user":"...","hash":"..."}
    # Root user hash = blake3("qwer.1234") 512-bit hex
    USERS: str = '[{"user":"root","hash":"9aa0a2b0f48247f8be3983b37fdbc13a4128da84d4a68ff6690d0202d8883c926f258640f9d8fad34f4b625043195da367307f04274618e734f7b5bf5641a663"}]'
    # DockLiner system version. Single source of truth for the running app.
    VERSION: str = "0.0.1"

    class Config:
        env_file = ".env"
        env_prefix = "DOCKLINER_"
        extra = "ignore"

settings = Settings()

# Parse users JSON
def _load_users():
    import json
    try:
        return json.loads(settings.USERS)
    except Exception:
        return []

ALLOWED_USERS = _load_users()

# Ensure dirs exist
Path(settings.PROJECTS_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.DOWNLOADS_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.LOGS_DIR).mkdir(parents=True, exist_ok=True)
