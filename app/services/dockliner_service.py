import os, subprocess, shutil, json, re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.core.config import settings

class DockLinerService:
    """Central service layer: Docker operations + project downloads."""

    # Cached docker executable path (expensive to resolve on Windows)
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
            # Common Docker Desktop Windows locations
            candidates = [
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
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
    def _run(cls, cmd: List[str], cwd: Optional[str] = None, timeout: int = 15) -> subprocess.CompletedProcess:
        """Run a shell command robustly.  Returns a synthetic failed result if docker is missing."""
        exe = cls._find_docker()
        if not exe:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="docker executable not found")
        resolved = [exe if c == "docker" else c for c in cmd]
        try:
            return subprocess.run(resolved, capture_output=True, text=True, cwd=cwd, timeout=timeout, check=False)
        except Exception as e:
            return subprocess.CompletedProcess(args=resolved, returncode=1, stdout="", stderr=str(e))

    # ---- Docker info ----
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
        r = cls._run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=15)
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
        r = cls._run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=60)
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
        r = cls._run(["docker", "stop", cid], timeout=30)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def remove_container(cls, cid: str, force: bool = False) -> tuple:
        cmd = ["docker", "rm", cid]
        if force:
            cmd.append("-f")
        r = cls._run(cmd, timeout=30)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def inspect_container_ports(cls, cid: str) -> List[Dict[str, Any]]:
        r = cls._run(["docker", "inspect", cid], timeout=15)
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
        r = cls._run(["docker", "logs", "--tail", str(tail), cid], timeout=15)
        return r.stdout + r.stderr

    @classmethod
    def container_top(cls, cid: str) -> List[Dict[str, Any]]:
        r = cls._run(["docker", "top", cid], timeout=15)
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
        r = cls._run(["docker", "images", "--format", "{{json .}}"], timeout=15)
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
        r = cls._run(cmd, timeout=30)
        return r.returncode, r.stdout + r.stderr

    # ---- Networks / Volumes ----
    @classmethod
    def list_networks(cls) -> List[Dict[str, Any]]:
        r = cls._run(["docker", "network", "ls", "--format", "{{json .}}"], timeout=15)
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
        r = cls._run(["docker", "volume", "ls", "--format", "{{json .}}"], timeout=15)
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
            # Prefer Docker Desktop CLI commands (no admin needed) then Windows service
            for ps_cmd in ["Start-Process -FilePath \"%ProgramFiles%\\Docker\\Docker\\Docker Desktop.exe\"", "Start-Service com.docker.service"]:
                r = subprocess.run(["powershell.exe", "-Command", ps_cmd], capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    return 0, "Docker Desktop start command sent."
            err = (r.stderr or r.stdout or "").strip()
            if "access is denied" in err.lower() or "cannot open" in err.lower() or "servicecontroller" in err.lower():
                return 1, "Permission denied: could not start Docker Desktop service. Please run PowerShell as Administrator, or start Docker Desktop manually from the Start menu."
            return r.returncode, err or "Could not start Docker daemon."
        r = subprocess.run(["sudo", "systemctl", "start", "docker"], capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def stop_daemon(cls) -> tuple:
        if os.name == "nt":
            # Try Docker Desktop CLI stop first, then Windows service
            for ps_cmd in ["Start-Process -FilePath \"%ProgramFiles%\\Docker\\Docker\\Docker Desktop.exe\" -ArgumentList \"--quit\"", "Stop-Service com.docker.service"]:
                r = subprocess.run(["powershell.exe", "-Command", ps_cmd], capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    return 0, "Docker Desktop stop command sent."
            err = (r.stderr or r.stdout or "").strip()
            if "access is denied" in err.lower() or "cannot open" in err.lower() or "servicecontroller" in err.lower():
                return 1, "Permission denied: could not stop Docker Desktop service. Please run PowerShell as Administrator and run: Stop-Service com.docker.service, or quit Docker Desktop from the system tray."
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
    def compose_up(cls, project_path: str, compose_file: Optional[str] = None) -> tuple:
        cmd = ["docker", "compose"] + cls._compose_file_arg(compose_file) + ["up", "-d", "--build"]
        r = cls._run(cmd, cwd=project_path, timeout=300)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def compose_down(cls, project_path: str, compose_file: Optional[str] = None) -> tuple:
        cmd = ["docker", "compose"] + cls._compose_file_arg(compose_file) + ["down"]
        r = cls._run(cmd, cwd=project_path, timeout=120)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def compose_logs(cls, project_path: str, compose_file: Optional[str] = None, tail: int = 200) -> str:
        cmd = ["docker", "compose"] + cls._compose_file_arg(compose_file) + ["logs", "--tail", str(tail)]
        r = cls._run(cmd, cwd=project_path, timeout=60)
        return r.stdout + r.stderr

    # ---- Dockerfile / direct helpers ----
    @classmethod
    def docker_build(cls, project_path: str, tag: str) -> tuple:
        cmd = ["docker", "build", "-t", tag, "."]
        r = cls._run(cmd, cwd=project_path, timeout=300)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def run_image(cls, tag: str, port: int) -> tuple:
        cmd = ["docker", "run", "-d", "-p", f"{port}:{port}", "--name", tag, tag]
        r = cls._run(cmd, timeout=60)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def run_shell_command(cls, project_path: str, command: str) -> tuple:
        r = cls._run(["bash", "-c", command], cwd=project_path, timeout=120)
        return r.returncode, r.stdout + r.stderr

    @classmethod
    def rsync_delete(cls, src: str, dst: str) -> tuple:
        # Fallback to robocopy on Windows and rsync elsewhere
        if os.name == "nt":
            dst_path = Path(dst)
            dst_path.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["robocopy", src, dst, "/MIR", "/MT:4"], capture_output=True, text=True, timeout=300)
            # robocopy exit codes 0-7 are generally success-ish
            rc = 0 if r.returncode <= 7 else r.returncode
            return rc, r.stdout + r.stderr
        r = subprocess.run(["rsync", "-a", "--delete", str(src) + "/", str(dst) + "/"], capture_output=True, text=True, timeout=300)
        return r.returncode, r.stdout + r.stderr

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
        for dl in rows:
            entry = dl.to_dict()
            entry.update(cls.scan_download(dl))
            out.append(entry)
        return out

    @classmethod
    def delete_download(cls, dl, db) -> None:
        if dl.extracted_path and Path(dl.extracted_path).exists():
            shutil.rmtree(dl.extracted_path, ignore_errors=True)
        if dl.download_path and Path(dl.download_path).exists():
            try:
                p = Path(dl.download_path)
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink()
            except Exception:
                pass
        db.delete(dl)
        db.commit()

    @classmethod
    def scan_download(cls, dl) -> Dict[str, Any]:
        from app.services.file_scanner import scan_downloaded_repo
        if not dl.extracted_path or not Path(dl.extracted_path).exists():
            return {"exists": False, "size_bytes": dl.size_bytes or 0, "total_bytes": dl.total_bytes, "compose_file": None, "dockerfile_exists": False, "env_exists": False, "example_env_exists": False}
        info = scan_downloaded_repo(dl.extracted_path)
        return {
            "exists": True,
            "size_bytes": info.get("size_bytes", 0),
            "compose_file": info.get("compose_file"),
            "dockerfile_exists": bool(info.get("dockerfile")),
            "env_exists": bool(info.get("env")),
            "example_env_exists": bool(info.get("example_env")),
        }

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
