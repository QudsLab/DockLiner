import os
import shutil
import datetime
from pathlib import Path
from typing import Optional
from app.core.config import settings
from app.services.git_service import GitService
from app.services.docker_service import DockerService
from app.models.project import Deployment

class DeployService:
    @staticmethod
    def deploy_project(project, token: Optional[str], db) -> Deployment:
        dep = Deployment(project_id=project.id, status="started", slot=project.active_slot)
        db.add(dep)
        db.commit()
        db.refresh(dep)
        logs = []

        try:
            # 1. Git clone/pull
            if project.github_repo_url:
                logs.append("Cloning repo...")
                cache = GitService.clone_or_pull(project.github_repo_url, project.branch or "main", token or "", project.name)
                logs.append(f"Cloned to cache: {cache}")
            else:
                cache = None
                logs.append("No repo configured; using existing deploy path.")

            deploy_path = Path(project.deploy_path)
            deploy_path.mkdir(parents=True, exist_ok=True)

            # 2. Blue-green slot switch
            active = project.active_slot or "blue"
            next_slot = "green" if active == "blue" else "blue"
            slot_path = deploy_path / next_slot
            slot_path.mkdir(parents=True, exist_ok=True)

            # 3. Rsync cache into slot
            if cache:
                logs.append(f"Syncing into {slot_path}...")
                rc, out = DockerService.rsync_delete(cache, str(slot_path))
                logs.append(out)
                if rc != 0:
                    raise RuntimeError("rsync failed: " + out)

            # 4. Write .env if any
            env_path = slot_path / ".env"
            env_data = project.env_vars or {}
            if env_data:
                lines = [f"{k}={v}" for k, v in env_data.items()]
                env_path.write_text("\n".join(lines) + "\n")
                logs.append("Wrote .env")

            # 5. Down old slot compose if exists
            old_slot_path = deploy_path / active
            if (old_slot_path / project.compose_file).exists():
                logs.append(f"Stopping old slot ({active})...")
                rc, out = DockerService.compose_down(str(old_slot_path), project.compose_file)
                logs.append(out)

            # 6. Up new slot
            logs.append(f"Starting new slot ({next_slot})...")
            rc, out = DockerService.compose_up(str(slot_path), project.compose_file)
            logs.append(out)
            if rc != 0:
                raise RuntimeError("compose up failed: " + out)

            # 7. Update project
            project.active_slot = next_slot
            if next_slot == "blue":
                project.blue_path = str(slot_path)
            else:
                project.green_path = str(slot_path)
            project.status = "running"
            project.last_deployed = datetime.datetime.utcnow()

            # 8. Cleanup cache
            cache_dir = Path(settings.GITHUB_CACHE) / project.name
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            rc, out = DockerService.system_prune()
            logs.append("Pruned docker system")

            dep.status = "success"
        except Exception as e:
            project.status = "error"
            dep.status = "error"
            logs.append(f"ERROR: {e}")

        dep.logs = "\n".join(logs)
        db.commit()
        db.refresh(dep)
        return dep

    @staticmethod
    def stop_project(project) -> str:
        slot = project.active_slot or "blue"
        slot_path = Path(project.deploy_path) / slot
        rc, out = DockerService.compose_down(str(slot_path), project.compose_file)
        project.status = "stopped"
        return out

    @staticmethod
    def restart_project(project) -> str:
        slot = project.active_slot or "blue"
        slot_path = Path(project.deploy_path) / slot
        rc, out = DockerService.compose_down(str(slot_path), project.compose_file)
        rc2, out2 = DockerService.compose_up(str(slot_path), project.compose_file)
        project.status = "running"
        return out + "\n" + out2