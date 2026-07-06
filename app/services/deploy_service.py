import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from git import Repo
from app.core.config import settings
from app.services.dockliner_service import DockLinerService
from app.models.project import Deployment

class DeployService:
    DEBUG = True  # always keep verbose debug logs for deployments

    @staticmethod
    def _debug(logs: list, msg: str) -> None:
        if DeployService.DEBUG:
            logs.append(f"[DEBUG] {msg}")

    @staticmethod
    def _clone_direct(project) -> None:
        deploy_path = Path(project.deploy_path)
        if deploy_path.exists():
            shutil.rmtree(deploy_path, ignore_errors=True)
        deploy_path.mkdir(parents=True, exist_ok=True)
        branch = project.branch or "main"
        url = project.github_repo_url or ""
        token = ""
        # If you later wire token lookup, replace this.
        if token and url.startswith("https://github.com/"):
            url = url.replace("https://", f"https://{token}@")
        Repo.clone_from(url, str(deploy_path), branch=branch, depth=1)

    @staticmethod
    def _sync_source(project) -> None:
        deploy_path = Path(project.deploy_path)
        deploy_path.mkdir(parents=True, exist_ok=True)

        if project.source_type == "download" and project.source_path:
            src = Path(project.source_path)
            if not src.exists():
                raise RuntimeError(f"download source missing: {src}")
            if deploy_path.exists():
                shutil.rmtree(deploy_path, ignore_errors=True)
            shutil.copytree(src, deploy_path)
        elif project.github_repo_url:
            DeployService._clone_direct(project)

    @staticmethod
    def _write_env(project) -> None:
        deploy_path = Path(project.deploy_path)
        env_path = deploy_path / ".env"
        env_data = dict(project.env_vars or {})
        env_data["DOCKLINER_HOST"] = os.getenv("DOCKLINER_HOST", os.getenv("HOSTNAME", "dockliner"))
        env_data["PROJECT_NAME"] = project.name
        if project.port:
            env_data["PORT"] = str(project.port)
        if env_data:
            lines = [f"{k}={v}" for k, v in env_data.items()]
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _persist_edited_files(project) -> None:
        deploy_path = Path(project.deploy_path)
        deploy_path.mkdir(parents=True, exist_ok=True)
        if project.env_content:
            (deploy_path / ".env").write_text(str(project.env_content), encoding="utf-8")
        if str(project.command_mode or project.deploy_method or "compose") == "compose" and project.compose_content:
            (deploy_path / str(project.compose_file or "compose.yml")).write_text(str(project.compose_content), encoding="utf-8")
        if str(project.command_mode or project.deploy_method or "compose") == "dockerfile" and project.dockerfile_content:
            (deploy_path / "Dockerfile").write_text(str(project.dockerfile_content), encoding="utf-8")
        if str(project.command_mode or "") == "direct" and project.direct_command:
            (deploy_path / "run.sh").write_text(str(project.direct_command), encoding="utf-8")

    @staticmethod
    def build(project, token: Optional[str] = None) -> list:
        logs = ["[BUILD] preparing source..."]
        try:
            DeployService._sync_source(project)
            DeployService._persist_edited_files(project)
            DeployService._write_env(project)
        except Exception as e:
            logs.append(f"[DEBUG] prepare error: {type(e).__name__}: {e}")
            raise

        deploy_path = Path(project.deploy_path)
        method = str(project.command_mode or project.deploy_method or "compose")
        DeployService._debug(logs, f"command_mode={method} compose_file={project.compose_file} deploy_path={deploy_path}")

        if method == "direct":
            logs.append("[BUILD] running direct command...")
            rc, out = DockLinerService.run_shell_command(str(deploy_path), str(project.direct_command or ""))
        elif method == "compose":
            logs.append("[BUILD] docker compose build...")
            rc, out = DockLinerService.compose_build(str(deploy_path), project.compose_file)
        else:
            logs.append("[BUILD] docker build...")
            rc, out = DockLinerService.docker_build(str(deploy_path), project.name)
        logs.append(out)
        DeployService._debug(logs, f"build rc={rc}")
        if rc != 0:
            raise RuntimeError("build failed: " + out)
        logs.append("[BUILD] done")
        return logs

    @staticmethod
    def up(project) -> list:
        logs = ["[DEPLOY] starting container..."]
        deploy_path = Path(project.deploy_path)
        method = str(project.command_mode or project.deploy_method or "compose")
        DeployService._debug(logs, f"up command_mode={method} compose_file={project.compose_file}")
        if method == "direct":
            rc, out = DockLinerService.run_shell_command(str(deploy_path), str(project.direct_command or ""))
        elif method == "compose":
            rc, out = DockLinerService.compose_up(str(deploy_path), project.compose_file)
        else:
            rc, out = DockLinerService.run_image(project.name, project.port or 0)
        logs.append(out)
        DeployService._debug(logs, f"deploy rc={rc}")
        if rc != 0:
            raise RuntimeError("deploy failed: " + out)
        logs.append("[DEPLOY] container started")
        return logs

    @staticmethod
    def quick_deploy(project, token: Optional[str] = None) -> list:
        logs = DeployService.build(project, token)
        logs += DeployService.up(project)
        return logs

    @staticmethod
    def deploy_project(project, token: Optional[str], db) -> Deployment:
        dep = Deployment(project_id=project.id, status="started")
        db.add(dep)
        db.commit()
        db.refresh(dep)
        logs = []
        try:
            logs = DeployService.quick_deploy(project, token)
            dep.status = "success"
        except Exception as e:
            dep.status = "error"
            logs.append(f"ERROR: {type(e).__name__}: {e}")
        dep.logs = "\n".join(logs)
        db.commit()
        return dep
