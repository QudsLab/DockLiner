import os
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict
from app.core.config import settings
from app.services.file_scanner import scan_downloaded_repo

class GitHubDownloadService:
    @staticmethod
    def download_repo(owner: str, repo: str, ref: str, token: str) -> Dict:
        url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{ref}"
        dl_dir = Path(settings.DOWNLOAD_DIR)
        dl_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = dl_dir / f"{owner}_{repo}_{ref}_{ts}"

        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "DockLiner"
        })

        zip_path = base.with_suffix(".zip")
        with urllib.request.urlopen(req, timeout=60) as resp:
            zip_path.write_bytes(resp.read())

        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(base)
        zip_path.unlink()

        # GitHub zipball has one root subfolder like owner-repo-commitsha/
        subdirs = [d for d in base.iterdir() if d.is_dir()]
        root = subdirs[0] if subdirs else base

        result = scan_downloaded_repo(str(root))
        result["download_root"] = str(base)
        return result
