import os
import shutil
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from app.core.config import settings
from app.models.project import Project

class CleanupService:
    @staticmethod
    def _human_size(n: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        i = 0
        while n >= 1024 and i < len(units) - 1:
            n /= 1024
            i += 1
        return f"{n:.1f} {units[i]}"

    @staticmethod
    def _folder_size(path: Path) -> int:
        total = 0
        for root, dirs, files in os.walk(str(path)):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass
        return total

    @staticmethod
    def _mtime(path: Path) -> datetime:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            return datetime.min

    @classmethod
    def scan_projects(cls, db) -> List[Dict[str, Any]]:
        root = Path(settings.PROJECTS_DIR)
        if not root.exists():
            return []
        registered = {str(Path(p.deploy_path).resolve()): p for p in db.query(Project).all() if p.deploy_path}
        registered_root = {str(Path(p.deploy_path).resolve().parent): p for p in db.query(Project).all() if p.deploy_path}
        orphans = []
        for folder in sorted(root.iterdir()):
            if not folder.is_dir():
                continue
            resolved = folder.resolve()
            matched = registered.get(str(resolved))
            if not matched:
                matched = registered_root.get(str(resolved))
            if matched:
                continue
            orphans.append({
                "type": "project",
                "path": str(resolved),
                "name": folder.name,
                "size_bytes": cls._folder_size(resolved),
                "size": cls._human_size(cls._folder_size(resolved)),
                "modified_at": cls._mtime(resolved).isoformat(),
            })
        return orphans

    @classmethod
    def scan_downloads(cls) -> List[Dict[str, Any]]:
        from app.core.db import SessionLocal
        from app.models.project import Download
        db = SessionLocal()
        try:
            tracked_paths = set()
            for dl in db.query(Download).all():
                if dl.extracted_path:
                    p = Path(dl.extracted_path).resolve()
                    tracked_paths.add(str(p))
                    if p.parent.name == Path(settings.DOWNLOADS_DIR).name:
                        tracked_paths.add(str(p.parent))
            root = Path(settings.DOWNLOADS_DIR)
            orphans = []
            if root.exists():
                for folder in sorted(root.iterdir()):
                    if not folder.is_dir():
                        continue
                    resolved = folder.resolve()
                    if str(resolved) in tracked_paths:
                        continue
                    orphans.append({
                        "type": "download",
                        "path": str(resolved),
                        "name": folder.name,
                        "size_bytes": cls._folder_size(resolved),
                        "size": cls._human_size(cls._folder_size(resolved)),
                        "modified_at": cls._mtime(resolved).isoformat(),
                    })
            return orphans
        finally:
            db.close()

    @classmethod
    def scan(cls, db) -> Dict[str, Any]:
        p = cls.scan_projects(db)
        d = cls.scan_downloads()
        total_size = sum(x["size_bytes"] for x in p + d)
        return {
            "projects": p,
            "downloads": d,
            "total_count": len(p) + len(d),
            "total_size": cls._human_size(total_size),
            "total_size_bytes": total_size,
        }

    @classmethod
    def delete_item(cls, item_type: str, name: str) -> bool:
        root = Path(settings.PROJECTS_DIR if item_type == "project" else settings.DOWNLOADS_DIR)
        target = (root / name).resolve()
        resolved_root = root.resolve()
        if not str(target).startswith(str(resolved_root)) or target == resolved_root:
            return False
        if not target.exists():
            return False
        DeployService = __import__("app.services.deploy_service", fromlist=["DeployService"]).DeployService
        DeployService._remove_tree(target)
        return not target.exists()

    @classmethod
    def bulk_delete(cls, items: List[Dict[str, str]]) -> Dict[str, Any]:
        deleted = 0
        failed = 0
        errors = []
        for item in items:
            ok = cls.delete_item(item.get("type", ""), item.get("name", ""))
            if ok:
                deleted += 1
            else:
                failed += 1
                errors.append(f"{item.get('type')}/{item.get('name')}")
        return {"deleted": deleted, "failed": failed, "errors": errors}
