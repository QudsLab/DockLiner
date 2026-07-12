import os
import shutil
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from app.core.config import settings
from app.services.dockliner_service import DockLinerService
from app.services.github_download_service import GitHubDownloadService
from app.models.project import Deployment, Download, AccessToken
from app.core.db import SessionLocal

class DeployService:
    DEBUG = True  # always keep verbose debug logs for deployments

    @staticmethod
    def _debug(logs: list, msg: str) -> None:
        if DeployService.DEBUG:
            logs.append(f"[DEBUG] {msg}")

    @staticmethod
    def _parse_github_url(url: str) -> tuple:
        """Parse https://github.com/owner/repo.git or https://github.com/owner/repo into (owner, repo)."""
        parsed = urlparse(str(url or ""))
        if parsed.netloc.lower() != "github.com":
            return None, None
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) < 2:
            return None, None
        owner = parts[0]
        repo = parts[1].replace(".git", "")
        return owner, repo

    @staticmethod
    def _ensure_github_source(project, token: Optional[str] = None) -> str:
        """For a github project, materialize the source once into downloads/ and return the extracted path."""
        if project.source_path:
            src = Path(project.source_path)
            if src.exists():
                return str(src)
        owner, repo = DeployService._parse_github_url(project.github_repo_url)
        if not owner or not repo:
            raise RuntimeError(f"invalid github repo url: {project.github_repo_url}")
        ref = project.branch or project.release_tag or "main"
        db = SessionLocal()
        try:
            # Find an existing successful download for this repo/ref.
            dl = (
                db.query(Download)
                .filter(Download.owner == owner, Download.repo == repo, Download.ref == ref, Download.status == "done")
                .order_by(Download.created_at.desc())
                .first()
            )
            if not dl:
                token_id = project.token_id
                if not token_id:
                    tok = db.query(AccessToken).first()
                    token_id = tok.id if tok else None
                dl = GitHubDownloadService.create_download(db, token_id or 0, owner, repo, ref)
                GitHubDownloadService.start_download(dl, token or "", db=db)
            if not dl.extracted_path or not Path(dl.extracted_path).exists():
                raise RuntimeError("github source download missing")
            return str(dl.extracted_path)
        finally:
            db.close()

    @staticmethod
    def _remove_tree(path: Path) -> None:
        """Remove a directory tree on Windows, handling read-only files and retries."""
        if not path.exists():
            return
        # Make everything writable first (Windows blocks deleting read-only files)
        for root, dirs, files in os.walk(str(path)):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o777)
                except Exception:
                    pass
            for f in files:
                try:
                    os.chmod(os.path.join(root, f), 0o777)
                except Exception:
                    pass
        try:
            shutil.rmtree(str(path), ignore_errors=False, onerror=None)
        except Exception:
            shutil.rmtree(str(path), ignore_errors=True)
        # If still present, rename and schedule deletion
        if path.exists():
            stale = path.parent / (path.name + ".stale")
            try:
                os.rename(str(path), str(stale))
                shutil.rmtree(str(stale), ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _sync_source(project, token: Optional[str] = None) -> None:
        deploy_path = Path(project.deploy_path)

        if project.source_type == "github":
            src = Path(DeployService._ensure_github_source(project, token))
        elif project.source_type == "download" and project.source_path:
            src = Path(project.source_path)
        elif project.source_type == "local" and project.source_path:
            src = Path(project.source_path)
        else:
            # No source to sync; leave deploy_path empty so edited files are the only content.
            deploy_path.mkdir(parents=True, exist_ok=True)
            return

        if not src.exists():
            raise RuntimeError(f"source missing: {src}")

        # Ensure a clean destination. copytree requires the destination not to exist.
        DeployService._remove_tree(deploy_path)
        # If the path is still locked as a directory, copy contents instead of the whole tree.
        if deploy_path.exists():
            # Fallback: overwrite existing files/directories in place.
            for item in src.iterdir():
                dest = deploy_path / item.name
                if dest.exists():
                    if item.is_dir():
                        DeployService._remove_tree(dest)
                    else:
                        try:
                            dest.unlink()
                        except Exception:
                            pass
                if item.is_dir():
                    if dest.exists():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
        else:
            shutil.copytree(src, deploy_path)

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
    def preview_commands(project) -> list:
        """Return the shell commands that Quick Deploy (build + up) will execute."""
        if project.deploy_commands:
            return list(project.deploy_commands)

        deploy_path = Path(project.deploy_path)
        method = str(project.command_mode or project.deploy_method or "compose")
        cmds = []

        # Source sync step: project folder is assumed ready, just sync/copy into deploy path.
        if project.source_type == "github":
            cmds.append(f"# sync source to {deploy_path}")
        elif project.source_type in ("download", "local") and project.source_path:
            cmds.append(f"cp -r {project.source_path} {deploy_path}")
        else:
            cmds.append(f"# no source configured; deploy_path left empty")

        # Env step
        cmds.append("# write .env")

        # Build step
        if method == "compose":
            compose_file = project.compose_file or "compose.yml"
            cmds.append(f"cd {deploy_path}")
            cmds.append(f"docker compose -f {compose_file} build")
        elif method == "dockerfile":
            cmds.append(f"cd {deploy_path}")
            cmds.append(f"docker build -t {project.name} .")
        elif method == "direct":
            cmds.append(f"cd {deploy_path}")
            cmd = project.direct_command or ""
            cmds.append(f"{cmd}" if cmd.strip() else "# no direct command provided")
        else:
            cmds.append("# unknown command mode")

        # Up/Run step
        if method == "compose":
            compose_file = project.compose_file or "compose.yml"
            cmds.append(f"docker compose -f {compose_file} up -d --build")
        elif method == "dockerfile":
            cmds.append(f"docker run -d -p {project.port or 0}:{project.port or 0} --name {project.name} {project.name}")
        # direct: run command is already the whole deploy, no separate up
        return cmds

    @staticmethod
    def build(project, token: Optional[str] = None) -> list:
        logs = ["[BUILD] preparing source..."]
        try:
            DeployService._sync_source(project, token)
            DeployService._persist_edited_files(project)
            DeployService._write_env(project)
        except Exception as e:
            logs.append(f"[DEBUG] prepare error: {type(e).__name__}: {e}")
            raise

        deploy_path = Path(project.deploy_path)
        method = str(project.command_mode or project.deploy_method or "compose")
        DeployService._debug(logs, f"command_mode={method} compose_file={project.compose_file} deploy_path={deploy_path}")

        if project.deploy_commands:
            logs.append("[BUILD] running custom deploy commands...")
            for cmd in project.deploy_commands:
                cmd = str(cmd).strip()
                if not cmd or cmd.startswith('#'):
                    continue
                logs.append(f"$ {cmd}")
                rc, out = DockLinerService.run_shell_command(str(deploy_path), cmd)
                logs.append(out)
                if rc != 0:
                    raise RuntimeError(f"command failed: {cmd}\n{out}")
            logs.append("[BUILD] done")
            return logs

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
        if project.deploy_commands:
            return ["[DEPLOY] custom deploy commands handled in build step"]
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
