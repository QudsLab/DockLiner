import os
import shutil
import subprocess
import uuid
import threading
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse
from app.core.config import settings
from app.services.dockliner_service import DockLinerService
from app.services.github_download_service import GitHubDownloadService
from app.models.project import Deployment, Download, AccessToken, OperationLog
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
    def preview_commands(project, mode: str = "deploy") -> list:
        """Return the shell commands that Quick Deploy (mode='deploy') or Build Image (mode='build') will execute."""
        if mode == "deploy" and project.deploy_commands:
            return list(project.deploy_commands)
        if mode == "build" and project.build_commands:
            return list(project.build_commands)

        deploy_path = Path(project.deploy_path)
        method = str(project.command_mode or project.deploy_method or "compose")
        cmds = []

        # Source sync step
        if project.source_type == "github":
            cmds.append(f"# sync source to {deploy_path}")
        elif project.source_type in ("download", "local") and project.source_path:
            cmds.append(f"cp -r {project.source_path} {deploy_path}")
        else:
            cmds.append(f"# no source configured; deploy_path left empty")

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

        if mode == "build":
            return cmds

        # Up/Run step for deploy mode
        if method == "compose":
            compose_file = project.compose_file or "compose.yml"
            cmds.append(f"docker compose -f {compose_file} up -d --build")
        elif method == "dockerfile":
            cmds.append(f"docker run -d --name {project.name} {project.name}")
        return cmds

    @staticmethod
    def _make_logger(project_id: int, op_type: str, op_key: str):
        def _log_line(line: str):
            db = SessionLocal()
            try:
                db.add(OperationLog(project_id=project_id, op_type=op_type, op_key=op_key, status="running", line=line))
                db.commit()
            finally:
                db.close()
        def _log_status(status: str, line: str = ""):
            db = SessionLocal()
            try:
                db.add(OperationLog(project_id=project_id, op_type=op_type, op_key=op_key, status=status, line=line))
                db.commit()
            finally:
                db.close()
        return _log_line, _log_status

    @staticmethod
    def _run_with_stream(cmd: list, cwd: str, log_line: Callable[[str], None]) -> int:
        process = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for raw in process.stdout:
            for line in raw.rstrip("\n").split("\r"):
                if line:
                    log_line(line)
        process.wait()
        return process.returncode

    @staticmethod
    def build_stream(project, op_key: str, token: Optional[str] = None):
        log_line, log_status = DeployService._make_logger(project.id, "build", op_key)
        try:
            log_status("running", "[BUILD] preparing source...")
            try:
                DeployService._sync_source(project, token)
                DeployService._persist_edited_files(project)
            except Exception as e:
                log_status("error", f"[DEBUG] prepare error: {type(e).__name__}: {e}")
                return

            deploy_path = Path(project.deploy_path)
            method = str(project.command_mode or project.deploy_method or "compose")
            DeployService._debug([], f"command_mode={method} compose_file={project.compose_file} deploy_path={deploy_path}")

            if project.build_commands:
                log_status("running", "[BUILD] running custom build commands...")
                for cmd in project.build_commands:
                    cmd = str(cmd).strip()
                    if not cmd or cmd.startswith('#'):
                        continue
                    log_line(f"$ {cmd}")
                    rc = DeployService._run_with_stream(["bash", "-c", cmd], str(deploy_path), log_line)
                    if rc != 0:
                        log_status("error", f"command failed: {cmd}")
                        return
                log_status("success", "[BUILD] done")
                return

            rc = 0
            if method == "direct":
                log_status("running", "[BUILD] running direct command...")
                rc = DeployService._run_with_stream(["bash", "-c", str(project.direct_command or "")], str(deploy_path), log_line)
            elif method == "compose":
                log_status("running", "[BUILD] docker compose build...")
                rc = DeployService._run_with_stream(["docker", "compose", "-f", str(project.compose_file or "compose.yml"), "build"], str(deploy_path), log_line)
            else:
                log_status("running", "[BUILD] docker build...")
                rc = DeployService._run_with_stream(["docker", "build", "-t", project.name, "."], str(deploy_path), log_line)
            if rc != 0:
                log_status("error", "[BUILD] failed")
                return
            log_status("success", "[BUILD] done")
        except Exception as e:
            log_status("error", f"[BUILD] unhandled exception: {type(e).__name__}: {e}")

    @staticmethod
    def quick_deploy_stream(project, op_key: str, token: Optional[str] = None):
        log_line, log_status = DeployService._make_logger(project.id, "deploy", op_key)
        try:
            log_status("running", "[DEPLOY] preparing source...")
            try:
                DeployService._sync_source(project, token)
                DeployService._persist_edited_files(project)
            except Exception as e:
                log_status("error", f"[DEBUG] prepare error: {type(e).__name__}: {e}")
                return

            deploy_path = Path(project.deploy_path)
            if project.deploy_commands:
                log_status("running", "[DEPLOY] running quick deploy commands...")
                for cmd in project.deploy_commands:
                    cmd = str(cmd).strip()
                    if not cmd or cmd.startswith('#'):
                        continue
                    log_line(f"$ {cmd}")
                    rc = DeployService._run_with_stream(["bash", "-c", cmd], str(deploy_path), log_line)
                    if rc != 0:
                        log_status("error", f"command failed: {cmd}")
                        return
                log_status("success", "[DEPLOY] done")
                return

            log_status("running", "[DEPLOY] starting container...")
            deploy_path = Path(project.deploy_path)
            method = str(project.command_mode or project.deploy_method or "compose")
            rc = 0
            if method == "direct":
                rc = DeployService._run_with_stream(["bash", "-c", str(project.direct_command or "")], str(deploy_path), log_line)
            elif method == "compose":
                rc = DeployService._run_with_stream(["docker", "compose", "-f", str(project.compose_file or "compose.yml"), "up", "-d", "--build"], str(deploy_path), log_line)
            else:
                rc = DeployService._run_with_stream(["docker", "run", "-d", "--name", project.name, project.name], str(deploy_path), log_line)
            if rc != 0:
                log_status("error", "[DEPLOY] failed")
                return
            log_status("success", "[DEPLOY] container started")
            from app.services.project_status_service import ProjectStatusService
            from app.core.db import SessionLocal
            db = SessionLocal()
            try:
                ProjectStatusService.record_deployed_fingerprint(db, project)
            finally:
                db.close()
        except Exception as e:
            log_status("error", f"[DEPLOY] unhandled exception: {type(e).__name__}: {e}")

    @staticmethod
    def up_stream(project, op_key: str):
        log_line, log_status = DeployService._make_logger(project.id, "deploy", op_key)
        try:
            if project.deploy_commands:
                log_status("success", "[DEPLOY] custom deploy commands handled in build step")
                return
            log_status("running", "[DEPLOY] starting container...")
            deploy_path = Path(project.deploy_path)
            method = str(project.command_mode or project.deploy_method or "compose")
            rc = 0
            if method == "direct":
                rc = DeployService._run_with_stream(["bash", "-c", str(project.direct_command or "")], str(deploy_path), log_line)
            elif method == "compose":
                rc = DeployService._run_with_stream(["docker", "compose", "-f", str(project.compose_file or "compose.yml"), "up", "-d", "--build"], str(deploy_path), log_line)
            else:
                rc = DeployService._run_with_stream(["docker", "run", "-d", "--name", project.name, project.name], str(deploy_path), log_line)
            if rc != 0:
                log_status("error", "[DEPLOY] failed")
                return
            log_status("success", "[DEPLOY] container started")
        except Exception as e:
            log_status("error", f"[DEPLOY] unhandled exception: {type(e).__name__}: {e}")

    @staticmethod
    def build(project, token: Optional[str] = None) -> list:
        logs = ["[BUILD] preparing source..."]
        try:
            DeployService._sync_source(project, token)
            DeployService._persist_edited_files(project)
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
            rc, out = DockLinerService.run_image(project.name, 0)
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
