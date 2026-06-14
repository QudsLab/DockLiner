import os
import shutil
from pathlib import Path
from git import Repo
from app.core.config import settings

class GitService:
    @staticmethod
    def clone_or_pull(repo_url: str, branch: str, token: str, name: str) -> str:
        cache_dir = Path(settings.GITHUB_CACHE) / name
        # Inject token into HTTPS URL if present
        auth_url = repo_url
        if token and repo_url.startswith("https://github.com/"):
            auth_url = repo_url.replace("https://", f"https://{token}@")
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        Repo.clone_from(auth_url, str(cache_dir), branch=branch, depth=1)
        return str(cache_dir)