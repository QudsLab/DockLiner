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
    def _build(project, token: Optional[str]) -> list:
        logs = []
        deploy_path = Path(project.deploy_path)
        deploy_path.mkdir(parents=True, exist_ok=True)

        # 1. Git clone/pull
        if project.github_repo_url:
            logs.append("Cloning repo...")
            branch = project.branch or "main"
            if project.release_tag:
                # For releases, clone then checkout tag
                cache = GitService.clone_or_pull(project.github_repo_url, branch, token or "", project.name)
                # Try to checkout the tag
                import subprocess
                subprocess.run(["git", "-C", cache, "fetch", "--tags", "--force"], capture_output=True)
                subprocess.run(["git", "-C", cache, "checkout", project.release_tag], capture_output=True)
                logs.append(f"Checked out tag {project.release_tag}")
            else:
                cache = GitService.clone_or_pull(project.github_repo_url, branch, token or "", project.name)
            logs.append(f"Cloned to cache: {cache}")
        else:
            cache = None
            logs.append("No repo configured; using existing deploy path.")

        # 2. Sync cache into deploy_path
        if cache:
            logs.append("Syncing into deploy path...")
            rc, out = DockerService.rsync_delete(cache, str(deploy_path))
            logs.append(out)
            if rc != 0:
                raise RuntimeError("rsync failed: " + out)

        # 3. Write .env
        env_path = deploy_path / ".env"
        env_data = dict(project.env_vars or {})
        env_data["DOCKLINER_HOST"] = os.getenv("DOCKLINER_HOST", os.getenv("HOSTNAME", "dockliner"))
        env_data["PROJECT_NAME"] = project.name
        if project.port:
            env_data["PORT"] = str(project.port)
        if env_data:
            lines = [f"{k}={v}" for k, v in env_data.items()]
            env_path.write_text("\n".join(lines) + "\n")
            logs.append("Wrote .env")

        # 4. Build
        if project.deploy_method == "compose":
            logs.append("Building compose...")
            rc, out = DockerService.compose_up(str(deploy_path), project.compose_file)
        else:
            logs.append("Building image...")
            rc, out = DockerService.docker_build(str(deploy_path), project.name)
        logs.append(out)
        if rc != 0:
            raise RuntimeError("build failed: " + out)

        # 5. Cleanup cache
        cache_dir = Path(settings.GITHUB_CACHE) / project.name
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        logs.append("Cleaned cache")

        return logs

    @staticmethod
    def deploy_project(project, token: Optional[str], db) -> Deployment:
        dep = Deployment(project_id=project.id, status="started")
        db.add(dep)
        db.commit()
        db.refresh(dep)
        logs = []
        try:
            logs += DeployService._build(project, token)
            project.status = "running"
            project.last_deployed = datetime.datetime.utcnow()
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
        deploy_path = Path(project.deploy_path)
        if project.deploy_method == "compose":
            rc, out = DockerService.compose_down(str(deploy_path), project.compose_file)
        else:
            rc, out = DockerService.stop_container_by_project(project.name)
        project.status = "stopped"
        return out

    @staticmethod
    def start_project(project) -> str:
        deploy_path = Path(project.deploy_path)
        if project.deploy_method == "compose":
            rc, out = DockerService.compose_up(str(deploy_path), project.compose_file)
        else:
            rc, out = DockerService.run_image(project.name, project.port or 8080)
        project.status = "running"
        return out

    @staticmethod
    def restart_project(project) -> str:
        out1 = DeployService.stop_project(project)
        out2 = DeployService.start_project(project)
        return out1 + "\n" + out2

    @staticmethod
    def project_logs(project, tail: int = 200) -> str:
        deploy_path = Path(project.deploy_path)
        if project.deploy_method == "compose":
            return DockerService.compose_logs(str(deploy_path), project.compose_file, tail)
        else:
            return DockerService.container_logs_by_project(project.name, tail)
