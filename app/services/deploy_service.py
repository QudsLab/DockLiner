import os
import shutil
import datetime
import subprocess
from pathlib import Path
from typing import Optional
from app.services.git_service import GitService
from app.services.dockliner_service import DockLinerService
from app.models.project import Deployment

class DeployService:
    DEBUG = True  # always keep verbose debug logs for deployments

    @staticmethod
    def _debug(logs: list, msg: str) -> None:
        if DeployService.DEBUG:
            logs.append(f"[DEBUG] {msg}")

    @staticmethod
    def _build(project, token: Optional[str]) -> list:
        logs = []
        deploy_path = Path(project.deploy_path)
        deploy_path.mkdir(parents=True, exist_ok=True)

        # 1. Materialize source files into deploy_path
        if project.github_repo_url:
            logs.append("Cloning repo...")
            branch = project.branch or "main"
            if project.release_tag:
                cache = GitService.clone_or_pull(project.github_repo_url, branch, token or "", project.name)
                subprocess.run(["git", "-C", cache, "fetch", "--tags", "--force"], capture_output=True)
                subprocess.run(["git", "-C", cache, "checkout", project.release_tag], capture_output=True)
                logs.append(f"Checked out tag {project.release_tag}")
            else:
                cache = GitService.clone_or_pull(project.github_repo_url, branch, token or "", project.name)
            logs.append(f"Cloned to cache: {cache}")
            DeployService._debug(logs, f"cache_dir={cache}")
            DeployService._debug(logs, f"deploy_path={deploy_path}")
            # Sync cache into deploy_path (mirror)
            logs.append("Syncing into deploy path...")
            rc, out = DockLinerService.rsync_delete(cache, str(deploy_path))
            logs.append(out)
            DeployService._debug(logs, f"rsync rc={rc}")
            if rc != 0:
                raise RuntimeError("rsync failed: " + out)
        elif project.source_type == "download" and project.source_path:
            src = Path(project.source_path)
            DeployService._debug(logs, f"source_type=download source_path={src}")
            if src.exists():
                logs.append(f"Copying download source {src} to deploy path...")
                if deploy_path.exists():
                    shutil.rmtree(deploy_path, ignore_errors=True)
                shutil.copytree(src, deploy_path)
            else:
                logs.append(f"Download source missing: {src}")
        else:
            DeployService._debug(logs, "no github_repo_url or download source; using existing deploy path")
            logs.append("No repo configured; using existing deploy path.")

        # 2. Write .env
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
            DeployService._debug(logs, f".env content:\n{env_path.read_text()}")

        # 3. Build/run
        method = str(project.command_mode or project.deploy_method or "compose")
        DeployService._debug(logs, f"command_mode={method} compose_file={project.compose_file}")
        if method == "direct":
            logs.append("Running direct command...")
            rc, out = DockLinerService.run_shell_command(str(deploy_path), str(project.direct_command or ""))
        elif method == "compose":
            logs.append("Building compose...")
            rc, out = DockLinerService.compose_up(str(deploy_path), project.compose_file)
        else:
            logs.append("Building image...")
            rc, out = DockLinerService.docker_build(str(deploy_path), project.name)
        logs.append(out)
        DeployService._debug(logs, f"build rc={rc}")
        if rc != 0:
            raise RuntimeError("build failed: " + out)

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
            DeployService._debug(logs, f"exception type={type(e).__name__}")
        dep.logs = "\n".join(logs)
        db.commit()
        db.refresh(dep)
        return dep

    @staticmethod
    def stop_project(project) -> str:
        deploy_path = Path(project.deploy_path)
        method = str(project.command_mode or project.deploy_method or "compose")
        if method == "compose":
            rc, out = DockLinerService.compose_down(str(deploy_path), project.compose_file)
        elif method == "direct":
            r = DockLinerService._run(["docker", "stop", project.name], timeout=10)
            rc, out = r.returncode, r.stdout + r.stderr
        else:
            rc, out = DockLinerService.stop_container(project.name)
        project.status = "stopped"
        return out

    @staticmethod
    def start_project(project) -> str:
        deploy_path = Path(project.deploy_path)
        method = str(project.command_mode or project.deploy_method or "compose")
        if method == "compose":
            rc, out = DockLinerService.compose_up(str(deploy_path), project.compose_file)
        elif method == "direct":
            rc, out = DockLinerService.run_shell_command(str(deploy_path), str(project.direct_command or ""))
        else:
            rc, out = DockLinerService.run_image(project.name, project.port or 8080)
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
            return DockLinerService.compose_logs(str(deploy_path), project.compose_file, tail)
        else:
            return DockLinerService.container_logs(project.name, tail)

    @staticmethod
    def quick_deploy(project, token: Optional[str], db) -> Deployment:
        """Deploy in one shot for repos or download sources."""
        return DeployService.deploy_project(project, token, db)

    @staticmethod
    def build_image(project, db) -> Deployment:
        """Build only (no start)."""
        dep = Deployment(project_id=project.id, status="started")
        db.add(dep)
        db.commit()
        db.refresh(dep)
        logs = []
        try:
            deploy_path = Path(project.deploy_path)
            deploy_path.mkdir(parents=True, exist_ok=True)
            DeployService._debug(logs, f"build_image deploy_path={deploy_path}")
            method = str(project.command_mode or project.deploy_method or "compose")
            if method == "compose":
                rc, out = DockLinerService.compose_build(str(deploy_path), project.compose_file)
            else:
                rc, out = DockLinerService.docker_build(str(deploy_path), project.name)
            logs.append(out)
            DeployService._debug(logs, f"build rc={rc}")
            if rc != 0:
                raise RuntimeError("build failed: " + out)
            dep.status = "success"
        except Exception as e:
            dep.status = "error"
            logs.append(f"ERROR: {e}")
        dep.logs = "\n".join(logs)
        db.commit()
        db.refresh(dep)
        return dep

    @staticmethod
    def run_container(project, db) -> Deployment:
        """Start an already-built project."""
        dep = Deployment(project_id=project.id, status="started")
        db.add(dep)
        db.commit()
        db.refresh(dep)
        logs = []
        try:
            out = DeployService.start_project(project)
            logs.append(out)
            dep.status = "success"
        except Exception as e:
            dep.status = "error"
            logs.append(f"ERROR: {e}")
        dep.logs = "\n".join(logs)
        db.commit()
        db.refresh(dep)
        return dep