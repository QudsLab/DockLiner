from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from urllib.request import Request, urlopen
from app.core.config import settings
from app.models.project import Download
from app.services.file_scanner import scan_downloaded_repo
import zipfile

class GitHubDownloadService:
    @staticmethod
    def _zip_url(owner: str, repo: str, ref: str) -> str:
        return f"https://api.github.com/repos/{owner}/{repo}/zipball/{ref}"

    @staticmethod
    def _base_dir(owner: str, repo: str, ref: str) -> Path:
        dl_dir = Path(settings.DOWNLOAD_DIR)
        dl_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return dl_dir / f"{owner}_{repo}_{ref}_{ts}"

    @staticmethod
    def create_download(db, token_id: int, owner: str, repo: str, ref: str) -> Download:
        dl = Download(
            token_id=token_id,
            owner=owner,
            repo=repo,
            ref=ref,
            status="pending",
            size_bytes=0,
        )
        db.add(dl)
        db.commit()
        db.refresh(dl)
        return dl

    @staticmethod
    def start_download(dl: Download, token: str, progress_callback=None) -> None:
        dl.status = "downloading"
        dl.updated_at = datetime.utcnow()

        base = GitHubDownloadService._base_dir(str(dl.owner), str(dl.repo), str(dl.ref))
        zip_path = base.with_suffix(".zip")
        dl.download_path = str(zip_path)

        req = Request(
            GitHubDownloadService._zip_url(str(dl.owner), str(dl.repo), str(dl.ref)),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "DockLiner",
            },
        )

        with urlopen(req, timeout=120) as resp:
            total = resp.headers.get("Content-Length")
            dl.total_bytes = int(total) if total else None
            block_size = 64 * 1024
            with open(zip_path, "wb") as f:
                while True:
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    current = dl.size_bytes
                    if current is None:
                        current = 0
                    current += len(chunk)
                    dl.size_bytes = current
                    if progress_callback:
                        progress_callback(dl)

        # Extract
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(base)
        zip_path.unlink()

        subdirs = [d for d in base.iterdir() if d.is_dir()]
        root = subdirs[0] if subdirs else base
        dl.extracted_path = str(root)
        dl.status = "done"
        dl.updated_at = datetime.utcnow()

    @staticmethod
    def run_download(dl_id, token: str, db, progress_callback=None) -> Download:
        dl = db.query(Download).filter(Download.id == dl_id).first()
        if not dl:
            raise ValueError("Download not found")
        try:
            GitHubDownloadService.start_download(dl, token, progress_callback)
            db.commit()
        except Exception as e:
            dl.status = "error"
            dl.error_message = str(e)
            dl.updated_at = datetime.utcnow()
            db.commit()
            raise
        return dl

    @staticmethod
    def scan(dl: Download) -> Dict:
        if not dl.extracted_path:
            return {}
        result = scan_downloaded_repo(dl.extracted_path)
        result["download_id"] = dl.id
        result["status"] = dl.status
        result["size_bytes"] = dl.size_bytes
        result["total_bytes"] = dl.total_bytes
        return result

    @staticmethod
    def delete_download(dl: Download, db) -> None:
        if dl.download_path:
            try:
                p = Path(dl.download_path)
                if p.exists():
                    if p.is_dir():
                        import shutil
                        shutil.rmtree(p)
                    else:
                        p.unlink()
            except Exception:
                pass
        if dl.extracted_path:
            try:
                import shutil
                shutil.rmtree(dl.extracted_path)
            except Exception:
                pass
        db.delete(dl)
        db.commit()
