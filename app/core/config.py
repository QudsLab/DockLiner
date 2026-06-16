import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_PATH: str = "./dockliner.db"
    PROJECTS_DIR: str = "./projects"
    DOWNLOAD_DIR: str = "./downloads"
    GITHUB_CACHE: str = "./github-cache"
    LOGS_DIR: str = "./logs"
    SECRET_KEY: str = "change-me"
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    MAX_ACCESS_TOKENS: int = 10
    # Default users as JSON array of {"user":"...","hash":"..."}
    # Root user hash = blake3("qwer.1234") 512-bit hex
    USERS: str = '[{"user":"root","hash":"9aa0a2b0f48247f8be3983b37fdbc13a4128da84d4a68ff6690d0202d8883c926f258640f9d8fad34f4b625043195da367307f04274618e734f7b5bf5641a663"}]'
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
Path(settings.DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.GITHUB_CACHE).mkdir(parents=True, exist_ok=True)
Path(settings.LOGS_DIR).mkdir(parents=True, exist_ok=True)