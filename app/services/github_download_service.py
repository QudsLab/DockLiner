from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from urllib.request import Request, urlopen
from app.core.config import settings
from app.models.project import Download
from app.services.file_scanner import scan_downloaded_repo
import zipfile
import threading
import hashlib

class GitHubDownloadService:
    _lock = threading.Lock()

    @staticmethod
    def _zip_url(owner: str, repo: str, ref: str) -> str:
        return f"https://api.github.com/repos/{owner}/{repo}/zipball/{ref}"

    @staticmethod
    def _base_dir(owner: str, repo: str, ref: str) -> Path:
        dl_dir = Path(settings.DOWNLOADS_DIR)
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
    def start_download(dl: Download, token: str, progress_callback=None, db=None) -> None:
        dl.status = "downloading"
        dl.updated_at = datetime.utcnow()
        if db:
            db.commit()

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

        last_commit = datetime.utcnow()
        h_md5 = hashlib.md5()
        h_sha256 = hashlib.sha256()
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
                    h_md5.update(chunk)
                    h_sha256.update(chunk)
                    current = dl.size_bytes or 0
                    dl.size_bytes = current + len(chunk)
                    # commit progress every ~1 second to avoid hammering the DB
                    now = datetime.utcnow()
                    if db and progress_callback and (now - last_commit).total_seconds() >= 1:
                        db.commit()
                        progress_callback(dl)
                        last_commit = now

        dl.md5_hash = h_md5.hexdigest()
        dl.sha256_hash = h_sha256.hexdigest()
        if db:
            db.commit()

        # Extract with tolerance for archive quirks (corrupt/mismatched members, etc.)
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(base)
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
            raise RuntimeError(f"Downloaded archive is corrupt: {e}")
        except RuntimeError as e:
            # Fallback: extract members individually, skipping problematic ones
            try:
                with zipfile.ZipFile(zip_path, "r") as z:
                    for member in z.infolist():
                        try:
                            z.extract(member, base)
                        except Exception:
                            pass
            except Exception:
                raise RuntimeError(f"Failed to extract archive: {e}")

        zip_path.unlink()

        subdirs = [d for d in base.iterdir() if d.is_dir()]
        root = subdirs[0] if subdirs else base
        dl.extracted_path = str(root)
        dl.status = "done"
        dl.updated_at = datetime.utcnow()
        if db:
            db.commit()
            if progress_callback:
                progress_callback(dl)

    @staticmethod
    def run_download(dl_id: int, token: str, db_factory, progress_callback=None) -> None:
        """Run a download in a background thread with its own DB session."""
        db = db_factory()
        try:
            dl = db.query(Download).filter(Download.id == dl_id).first()
            if not dl:
                return
            try:
                GitHubDownloadService.start_download(dl, token, progress_callback=progress_callback, db=db)
            except Exception as e:
                dl.status = "error"
                dl.error_message = str(e)
                dl.updated_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    @staticmethod
    def run_download_sync(dl: Download, token: str, db, progress_callback=None) -> Download:
        """Synchronous wrapper kept for compatibility."""
        try:
            GitHubDownloadService.start_download(dl, token, progress_callback=progress_callback, db=db)
            db.commit()
        except Exception as e:
            dl.status = "error"
            dl.error_message = str(e)
            dl.updated_at = datetime.utcnow()
            db.commit()
            raise
        return dl

    @staticmethod
    def get_status(dl_id: int, db) -> Optional[dict]:
        dl = db.query(Download).filter(Download.id == dl_id).first()
        if not dl:
            return None
        out = dl.to_dict()
        out.update(GitHubDownloadService.scan(dl))
        return out

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
    def backfill_hashes(dl: Download, db) -> bool:
        """Compute md5/sha256 for an existing download. Prefer the zip archive; fall back to walking the extracted project directory."""
        if dl.md5_hash and dl.sha256_hash:
            return True
        zip_path = dl.download_path
        if zip_path:
            p = Path(zip_path)
            if p.exists():
                try:
                    h_md5 = hashlib.md5()
                    h_sha256 = hashlib.sha256()
                    with open(p, "rb") as f:
                        while True:
                            chunk = f.read(1024 * 1024)
                            if not chunk:
                                break
                            h_md5.update(chunk)
                            h_sha256.update(chunk)
                    dl.md5_hash = h_md5.hexdigest()
                    dl.sha256_hash = h_sha256.hexdigest()
                    dl.updated_at = datetime.utcnow()
                    db.commit()
                    return True
                except Exception:
                    pass
        extracted = dl.extracted_path
        if extracted:
            p = Path(extracted)
            if p.exists() and p.is_dir():
                try:
                    h_md5 = hashlib.md5()
                    h_sha256 = hashlib.sha256()
                    files = sorted([fp for fp in p.rglob("*") if fp.is_file() and not any(part.startswith(".") for part in fp.relative_to(p).parts)])
                    for fp in files:
                        rel = fp.relative_to(p).as_posix() + "\n"
                        h_md5.update(rel.encode())
                        h_sha256.update(rel.encode())
                        with open(fp, "rb") as f:
                            while True:
                                chunk = f.read(1024 * 1024)
                                if not chunk:
                                    break
                                h_md5.update(chunk)
                                h_sha256.update(chunk)
                    dl.md5_hash = h_md5.hexdigest()
                    dl.sha256_hash = h_sha256.hexdigest()
                    dl.updated_at = datetime.utcnow()
                    db.commit()
                    return True
                except Exception:
                    return False
        return False

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
