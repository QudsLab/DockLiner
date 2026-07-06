import os
import shutil
import json
import time
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.core.config import settings
from app.services.file_scanner import scan_downloaded_repo

class DockLinerService:
    """Central service layer: Docker operations + project downloads."""

    _docker_exe: Optional[str] = None

    @classmethod
    def _find_docker(cls) -> Optional[str]:
        if cls._docker_exe is not None:
            return cls._docker_exe
        exe: Optional[str] = None
        if settings.DOCKER_EXECUTABLE:
            if Path(str(settings.DOCKER_EXECUTABLE)).exists():
                exe = str(settings.DOCKER_EXECUTABLE)
        if not exe:
            exe = shutil.which("docker")
        if not exe and os.name == "nt":
            candidates = [
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "docker.exe",
                Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Ahmad Bin Haque\AppData\Local")) / "Microsoft" / "WindowsApps" / "docker.exe",
                Path(r"C:\ProgramData\DockerDesktop\version-bin") / "docker.exe",
            ]
            for c in candidates:
                if c.exists():
                    exe = str(c)
                    break
        cls._docker_exe = exe
        return exe

    @classmethod
    def _wait_for_daemon(cls, timeout: int = 20) -> bool:
        exe = cls._find_docker()
        if not exe:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = subprocess.run([exe, "info"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return True
            time.sleep(1)
        return False

    @classmethod
    def _diagnose(cls, err: str) -> str:
        err_l = err.lower()
        if os.name == "nt" and ("cannot find the file specified" in err or "npipe" in err_l or "named pipe" in err_l):
            return "Docker Desktop is not running or the Windows named pipe is not available. Start Docker Desktop and make sure it is set to Linux containers."
        if "dockerdesktoplinuxengine" in err_l:
            return "Docker Desktop is using the wrong engine context. Switch to Linux containers or set DOCKER_HOST to the default pipe."
        if "permission denied" in err_l:
            if os.name == "nt":
                return "Permission denied accessing Docker. Run the terminal as Administrator."
            return "Permission denied accessing Docker. Add your user to the `docker` group or use sudo."
        if "connection refused" in err_l or "is the docker daemon running" in err_l:
            return "Docker daemon is not reachable. Start Docker and try again."
        return err.strip() or "Docker command failed."

    @classmethod
    def _run(cls, cmd: List[str], cwd: Optional[str] = None, timeout: int = 15) -> subprocess.CompletedProcess:
        exe = cls._find_docker()
        if not exe:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Docker executable not found. Install Docker Desktop (Windows/Mac) or docker-ce (Linux) and restart DockLiner.")
        resolved = [exe if c == "docker" else c for c in cmd]
        try:
            r = subprocess.run(resolved, capture_output=True, text=True, cwd=cwd, timeout=timeout, check=False)
        except Exception as e:
            return subprocess.CompletedProcess(args=resolved, returncode=1, stdout="", stderr=str(e))
        if r.returncode != 0 and r.stderr:
            r._dockliner_diag = cls._diagnose(r.stderr)  # type: ignore[attr-defined]
        return r

    @classmethod
    def _with_preflight(cls, cmd: List[str], cwd: Optional[str] = None, timeout: int = 300) -> subprocess.CompletedProcess:
        if not cls.docker_installed():
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Docker is not installed. Install Docker Desktop (Windows/Mac) or docker-ce (Linux) and restart DockLiner.")
        if not cls.docker_running():
            if not cls._wait_for_daemon(timeout=15):
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Docker daemon is not running. Start Docker Desktop (Windows/Mac) or run `sudo systemctl start docker` (Linux).")
        return cls._run(cmd, cwd=cwd, timeout=timeout)

    @classmethod
    def docker_installed(cls) -> bool:
        return cls._find_docker() is not None

    @classmethod
    def docker_running(cls) -> bool:
        r = cls._run(["docker", "info"], timeout=5)
        return r.returncode == 0

    @classmethod
    def docker_version(cls) -> str:
        r = cls._run(["docker", "version", "--format", "{{.Client.Version}}"], timeout=5)
        return r.stdout.strip() if r.returncode == 0 else "unknown"

    # ---- Containers ----
    @classmethod
    def list_containers(cls) -> List[Dict[str, Any]]:
        r = cls._with_preflight(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=15)
        out: List[Dict[str, Any]] = []
        if r.returncode != 0:
            return out
        for line in r.stdout.strip().splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out

    @classmethod
    def container_stats(cls) -> List[Dict[str, Any]]:
        r = cls._with_preflight(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=60)
        out: List[Dict[str, Any]] = []
        if r.returncode != 0:
            return out
        for line in r.stdout.strip().splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out

    @classmethod
    def stop_container(cls, cid: str) -> tuple:
        r = cls._with_preflight(["docker", "stop", cid], timeout=30)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return r.returncode, r.stdout + (err if r.returncode != 0 else "")

    @classmethod
    def remove_container(cls, cid: str, force: bool = False) -> tuple:
        cmd = ["docker", "rm", cid]
        if force:
            cmd.append("-f")
        r = cls._with_preflight(cmd, timeout=30)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return r.returncode, r.stdout + (err if r.returncode != 0 else "")

    @classmethod
    def inspect_container_ports(cls, cid: str) -> List[Dict[str, Any]]:
        r = cls._with_preflight(["docker", "inspect", cid], timeout=15)
        if r.returncode != 0:
            return []
        try:
            data = json.loads(r.stdout)
            bindings = data[0].get("NetworkSettings", {}).get("Ports", {})
            out = []
            for k, v in bindings.items():
                out.append({"container": k, "host": v[0]["HostIp"] + ":" + v[0]["HostPort"] if v else None})
            return out
        except Exception:
            return []

    @classmethod
    def container_logs(cls, cid: str, tail: int = 200) -> str:
        r = cls._with_preflight(["docker", "logs", "--tail", str(tail), cid], timeout=15)
        if r.returncode != 0:
            diag = getattr(r, "_dockliner_diag", r.stderr)
            return f"Docker error: {diag}"
        return r.stdout + r.stderr

    @classmethod
    def container_top(cls, cid: str) -> List[Dict[str, Any]]:
        r = cls._with_preflight(["docker", "top", cid], timeout=15)
        if r.returncode != 0:
            return []
        lines = r.stdout.strip().splitlines()
        if not lines:
            return []
        headers = lines[0].split()
        return [dict(zip(headers, row.split(None, len(headers)-1))) for row in lines[1:]]

    # ---- Images ----
    @classmethod
    def list_images(cls) -> List[Dict[str, Any]]:
        r = cls._with_preflight(["docker", "images", "--format", "{{json .}}"], timeout=15)
        out = []
        if r.returncode != 0:
            return out
        for line in r.stdout.strip().splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out

    @classmethod
    def remove_image(cls, iid: str, force: bool = False) -> tuple:
        cmd = ["docker", "rmi", iid]
        if force:
            cmd.append("-f")
        r = cls._with_preflight(cmd, timeout=30)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return r.returncode, r.stdout + (err if r.returncode != 0 else "")

    # ---- Networks / Volumes ----
    @classmethod
    def list_networks(cls) -> List[Dict[str, Any]]:
        r = cls._with_preflight(["docker", "network", "ls", "--format", "{{json .}}"], timeout=15)
        out = []
        if r.returncode != 0:
            return out
        for line in r.stdout.strip().splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out

    @classmethod
    def list_volumes(cls) -> List[Dict[str, Any]]:
        r = cls._with_preflight(["docker", "volume", "ls", "--format", "{{json .}}"], timeout=15)
        out = []
        if r.returncode != 0:
            return out
        for line in r.stdout.strip().splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out

    # ---- Docker daemon control ----
    @classmethod
    def start_daemon(cls) -> tuple:
        if os.name == "nt":
            dd = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"
            if dd.exists():
                subprocess.Popen([str(dd)], shell=False)
                if cls._wait_for_daemon(timeout=30):
                    return 0, "Docker Desktop started"
            return 1, "Could not start Docker Desktop. Start it manually from the system tray."
        r = subprocess.run(["sudo", "systemctl", "start", "docker"], capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def stop_daemon(cls) -> tuple:
        if os.name == "nt":
            for ps_cmd in ["Start-Process -FilePath \"%ProgramFiles%\\Docker\\Docker\\Docker Desktop.exe\" -ArgumentList \"--quit\"", "Stop-Service com.docker.service"]:
                r = subprocess.run(["powershell.exe", "-Command", ps_cmd], capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    return 0, "Docker Desktop stop command sent."
            err = (r.stderr or r.stdout or "").strip()
            if "access is denied" in err.lower() or "cannot open" in err.lower() or "servicecontroller" in err.lower():
                return 1, "Permission denied: could not stop Docker Desktop service. Run PowerShell as Administrator."
            return r.returncode, err or "Could not stop Docker daemon."
        r = subprocess.run(["sudo", "systemctl", "stop", "docker"], capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr

    # ---- Security ----
    @classmethod
    def security_summary(cls) -> Dict[str, Any]:
        c = cls.list_containers()
        issues = []
        for cnt in c:
            if cnt.get("Image") == "latest":
                issues.append({"container": cnt.get("Names"), "issue": "uses 'latest' tag"})
        return {"containers_checked": len(c), "issues": issues, "score": max(0, 100 - len(issues) * 10)}

    # ---- Compose helpers ----
    @staticmethod
    def _compose_file_arg(compose_file: Optional[str]) -> List[str]:
        if compose_file and compose_file.strip():
            return ["-f", compose_file.strip()]
        return []

    @classmethod
    def compose_build(cls, project_path: str, compose_file: Optional[str] = None) -> tuple:
        cmd = ["docker", "compose"] + cls._compose_file_arg(compose_file) + ["build"]
        r = cls._with_preflight(cmd, cwd=project_path, timeout=300)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return r.returncode, r.stdout + (err if r.returncode != 0 else "")

    @classmethod
    def compose_up(cls, project_path: str, compose_file: Optional[str] = None) -> tuple:
        cmd = ["docker", "compose"] + cls._compose_file_arg(compose_file) + ["up", "-d", "--build"]
        r = cls._with_preflight(cmd, cwd=project_path, timeout=300)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return r.returncode, r.stdout + (err if r.returncode != 0 else "")

    @classmethod
    def compose_down(cls, project_path: str, compose_file: Optional[str] = None) -> tuple:
        cmd = ["docker", "compose"] + cls._compose_file_arg(compose_file) + ["down"]
        r = cls._with_preflight(cmd, cwd=project_path, timeout=120)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return r.returncode, r.stdout + (err if r.returncode != 0 else "")

    @classmethod
    def compose_logs(cls, project_path: str, compose_file: Optional[str] = None, tail: int = 200) -> str:
        cmd = ["docker", "compose"] + cls._compose_file_arg(compose_file) + ["logs", "--tail", str(tail)]
        r = cls._with_preflight(cmd, cwd=project_path, timeout=60)
        if r.returncode != 0:
            diag = getattr(r, "_dockliner_diag", r.stderr)
            return f"Docker error: {diag}"
        return r.stdout + r.stderr

    # ---- Dockerfile / direct helpers ----
    @classmethod
    def docker_build(cls, project_path: str, tag: str) -> tuple:
        cmd = ["docker", "build", "-t", tag, "."]
        r = cls._with_preflight(cmd, cwd=project_path, timeout=300)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return r.returncode, r.stdout + (err if r.returncode != 0 else "")

    @classmethod
    def run_image(cls, tag: str, port: int) -> tuple:
        cmd = ["docker", "run", "-d", "-p", f"{port}:{port}", "--name", tag, tag]
        r = cls._with_preflight(cmd, timeout=60)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return r.returncode, r.stdout + (err if r.returncode != 0 else "")

    @classmethod
    def run_shell_command(cls, project_path: str, command: str) -> tuple:
        if not command.strip():
            return (1, "No direct command provided")
        r = cls._run(["bash", "-c", command], cwd=project_path, timeout=120)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def rsync_delete(cls, src: str, dst: str) -> tuple:
        src_p = Path(src)
        dst_p = Path(dst)
        if not src_p.exists():
            return (1, f"Source path does not exist: {src}")
        try:
            if dst_p.exists():
                shutil.rmtree(dst_p)
            shutil.copytree(src_p, dst_p)
            return (0, "synced")
        except Exception as e:
            return (1, f"sync failed: {e}")

    # ---- Directories ----
    @classmethod
    def ensure_dirs(cls) -> None:
        Path(settings.PROJECTS_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.GITHUB_CACHE).mkdir(parents=True, exist_ok=True)
        Path(settings.DOWNLOADS_DIR).mkdir(parents=True, exist_ok=True)

    # ---- Downloads ----
    @classmethod
    def list_downloads(cls, db) -> List[Dict[str, Any]]:
        from app.models.project import Download
        rows = db.query(Download).order_by(Download.created_at.desc()).all()
        out = []
        db_by_folder: Dict[str, Download] = {}
        for dl in rows:
            entry = dl.to_dict()
            try:
                entry.update(cls.scan_download(dl))
            except Exception:
                entry.update({"exists": False, "compose_file": None, "dockerfile_exists": False, "env_exists": False, "example_env_exists": False})
            out.append(entry)
            if dl.extracted_path:
                p = Path(dl.extracted_path)
                db_by_folder[p.name] = dl
                if p.parent.name == Path(settings.DOWNLOADS_DIR).name or str(p.parent) == str(Path(settings.DOWNLOADS_DIR)):
                    db_by_folder[p.parent.name] = dl

        # Merge physical folders without DB record as untracked entries.
        downloads_root = Path(settings.DOWNLOADS_DIR)
        if downloads_root.exists():
            for folder in sorted(downloads_root.iterdir()):
                if not folder.is_dir() or folder.name in db_by_folder:
                    continue
                scan_target = folder
                subdirs = [d for d in folder.iterdir() if d.is_dir()]
                if len(subdirs) == 1:
                    inner = subdirs[0]
                    if any((inner / f).exists() for f in ['compose.yml','compose.yaml','docker-compose.yml','docker-compose.yaml','Dockerfile']):
                        scan_target = inner
                info = scan_downloaded_repo(str(scan_target))
                out.append({
                    "id": None,
                    "token_id": None,
                    "owner": "",
                    "repo": scan_target.name,
                    "ref": "",
                    "status": "untracked",
                    "size_bytes": info.get("size_bytes", 0),
                    "total_bytes": None,
                    "error_message": "",
                    "download_path": None,
                    "extracted_path": str(scan_target),
                    "md5_hash": None,
                    "sha256_hash": None,
                    "created_at": None,
                    "updated_at": None,
                    "exists": True,
                    "compose_file": info.get("compose_file"),
                    "dockerfile_exists": bool(info.get("dockerfile")),
                    "env_exists": bool(info.get("env")),
                    "example_env_exists": bool(info.get("example_env")),
                })
        return out

    @classmethod
    def scan_download(cls, dl) -> Dict[str, Any]:
        if not dl.extracted_path or not Path(dl.extracted_path).exists():
            return {"exists": False, "compose_file": None, "dockerfile_exists": False, "env_exists": False, "example_env_exists": False}
        info = scan_downloaded_repo(dl.extracted_path)
        return {
            "exists": True,
            "compose_file": info.get("compose_file"),
            "dockerfile_exists": bool(info.get("dockerfile")),
            "env_exists": bool(info.get("env")),
            "example_env_exists": bool(info.get("example_env")),
        }

    @classmethod
    def delete_download(cls, dl, db) -> None:
        # Remove the whole outer download container, not just the inner extracted folder.
        if dl.extracted_path:
            p = Path(dl.extracted_path).resolve()
            root = Path(settings.DOWNLOADS_DIR).resolve()
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
            if str(p).startswith(str(root)) and p != root and p.parent != root:
                try:
                    if p.parent.exists():
                        shutil.rmtree(p.parent, ignore_errors=True)
                except Exception:
                    pass
        if dl.download_path and Path(dl.download_path).exists():
            try:
                pp = Path(dl.download_path)
                if pp.is_dir():
                    shutil.rmtree(pp, ignore_errors=True)
                else:
                    pp.unlink()
            except Exception:
                pass
        db.delete(dl)
        db.commit()

    @classmethod
    def delete_download_folder(cls, folder_name: str) -> bool:
        """Delete an untracked download folder directly from disk."""
        downloads_root = Path(settings.DOWNLOADS_DIR)
        target = downloads_root / folder_name
        try:
            resolved = target.resolve()
            root = downloads_root.resolve()
            if not str(resolved).startswith(str(root)) or resolved == root:
                return False
            if resolved.exists():
                shutil.rmtree(resolved, ignore_errors=True)
            return True
        except Exception:
            return False

    # ---- Deprecated aliases kept for compatibility ----
    @classmethod
    def docker_info(cls) -> Dict[str, Any]:
        r = cls._run(["docker", "info", "--format", "json"], timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            try:
                return json.loads(r.stdout.strip())
            except Exception:
                pass
        return {}

    @classmethod
    def download_size(cls, dl) -> int:
        if not dl.extracted_path or not Path(dl.extracted_path).exists():
            return 0
        total = 0
        for root, dirs, files in os.walk(dl.extracted_path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass
        return total
