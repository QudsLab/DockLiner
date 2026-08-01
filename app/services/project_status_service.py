import datetime
import hashlib
import os
from pathlib import Path
from typing import Dict, Any, Optional

from app.services.docker_service import DockerService
from app.services.system_resources_service import SystemResourcesService


class ProjectStatusService:
    """Single source of truth for project/container/build status."""

    @staticmethod
    def project_fingerprint(project) -> tuple[str, int]:
        """Return (hash, size_bytes) for all files under the project deploy path.
        Uses relative path, size and mtime so any change is detected quickly."""
        root = Path(str(project.deploy_path)).resolve()
        total_size = 0
        entries = []
        if root.exists():
            for p in root.rglob("*"):
                try:
                    if p.is_file():
                        rel = p.relative_to(root).as_posix()
                        st = p.stat()
                        entries.append((rel, st.st_size, int(st.st_mtime)))
                        total_size += st.st_size
                except (OSError, ValueError):
                    continue
        entries.sort()
        digest = hashlib.sha256(str(entries).encode("utf-8")).hexdigest()[:32]
        return digest, total_size

    @staticmethod
    def record_deployed_fingerprint(db, project) -> Dict[str, Any]:
        h, size = ProjectStatusService.project_fingerprint(project)
        project.deployed_hash = h
        project.deployed_size = size
        db.commit()
        return {"hash": h, "size": size}

    @staticmethod
    def files_changed_since_deploy(project) -> bool:
        if not project.deployed_hash:
            return False
        h, size = ProjectStatusService.project_fingerprint(project)
        return h != project.deployed_hash or size != (project.deployed_size or 0)

    @staticmethod
    def _project_name_from_path(deploy_path: str) -> str:
        return Path(str(deploy_path)).name

    @staticmethod
    def find_project_containers(project) -> list:
        """Return Docker containers that belong to this project's compose deployment."""
        proj_name = ProjectStatusService._project_name_from_path(project.deploy_path)
        needle_name = proj_name.replace("-", "_")
        # Docker Compose lower-cases the project name in labels.
        needle_label = needle_name.lower()
        containers = DockerService.list_containers()
        out = []
        for c in containers:
            names = c.get("Names") or c.get("Name") or ""
            labels = c.get("Labels") or ""
            if needle_name in names or needle_label in labels.lower():
                out.append(c)
            elif ("project=" in labels or "project.working_dir=" in labels) and project.deploy_path.lower().replace("\\", "/") in labels.lower():
                out.append(c)
        return out

    @staticmethod
    def container_state(project) -> Dict[str, Any]:
        """Return running container status: exists, state, container dict."""
        related = ProjectStatusService.find_project_containers(project)
        running = [c for c in related if (c.get("State") or "").lower() == "running"]
        if running:
            return {"exists": True, "state": "running", "container": running[0], "all": related}
        if related:
            state = (related[0].get("State") or "created").lower()
            return {"exists": True, "state": state, "container": related[0], "all": related}
        return {"exists": False, "state": "idle", "container": None, "all": []}

    @staticmethod
    def container_status_label(project) -> str:
        state = ProjectStatusService.container_state(project)
        label = state["state"]
        # Normalize Docker states to our UI vocabulary.
        if not state["exists"]:
            return "idle"
        if label in ("running",):
            return "running"
        if label in ("exited", "dead"):
            return "stopped"
        if label in ("paused",):
            return "paused"
        if label in ("restarting",):
            return "restarting"
        return label  # created, etc.

    @staticmethod
    def build_status_from_db(db, project) -> str:
        from app.models.project import OperationLog
        row = (
            db.query(OperationLog)
            .filter(OperationLog.project_id == project.id, OperationLog.op_type == "build")
            .order_by(OperationLog.id.desc())
            .first()
        )
        if not row:
            return "not_built"
        if row.status == "success":
            return "build_success"
        if row.status == "error":
            return "build_failed"
        return "building"

    @staticmethod
    def sync_status(db, project, commit: bool = True) -> Dict[str, str]:
        """Sync project.status with actual Docker state and return both labels."""
        # Always read fresh container state; cache is cleared after lifecycle ops.
        container_label = ProjectStatusService.container_status_label(project)
        build_label = ProjectStatusService.build_status_from_db(db, project)
        target = container_label
        if project.status != target:
            project.status = target
            if commit:
                db.commit()
        return {"container_status": container_label, "build_status": build_label}

    @staticmethod
    def container_resource_stats(project) -> Dict[str, Optional[float]]:
        """Return CPU/RAM from container Docker stats; GPU/ROM fallback to host resources."""
        result: Dict[str, Optional[float]] = {"cpu": None, "ram": None, "disk": None, "gpu": None}
        state = ProjectStatusService.container_state(project)
        if state["exists"] and state["state"] == "running":
            cid = state["container"].get("ID", "")
            all_stats = DockerService.system_stats()
            stats = next((s for s in all_stats if s.get("Container") == cid or s.get("ID") == cid), None)
            if stats:
                def parse_percent(raw):
                    if raw is None:
                        return None
                    try:
                        return float(str(raw).replace("%", "").strip())
                    except Exception:
                        return None
                result["cpu"] = parse_percent(stats.get("CPUPerc"))
                result["ram"] = parse_percent(stats.get("MemPerc"))

        # Host-level fallbacks for GPU and ROM; also fill CPU/RAM if container stats unavailable.
        try:
            host = SystemResourcesService.get()
            if result["cpu"] is None:
                result["cpu"] = host.get("cpu")
            if result["ram"] is None:
                result["ram"] = host.get("ram")
            result["gpu"] = host.get("gpu")
            result["disk"] = host.get("disk")
        except Exception:
            pass
        return result
