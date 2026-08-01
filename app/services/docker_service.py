import os
import shutil
import json
import re
import time
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

class DockerService:
    """Cross-platform Docker CLI wrapper with clear, actionable error messages."""
    _docker_exe: Optional[str] = None
    _docker_ready: Optional[bool] = None
    _cache: Dict[str, Any] = {}
    _cache_ttl: float = 3.0  # seconds; short enough to stay fresh, long enough to avoid repeated CLI hits

    @classmethod
    def _cache_get(cls, key: str) -> Any:
        entry = cls._cache.get(key)
        if entry and (time.time() - entry[0]) < cls._cache_ttl:
            return entry[1]
        return None

    @classmethod
    def _cache_set(cls, key: str, value: Any) -> None:
        cls._cache[key] = (time.time(), value)

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    @staticmethod
    def _find_docker() -> Optional[str]:
        if DockerService._docker_exe is None:
            exe = shutil.which("docker")
            if not exe and os.name == "nt":
                for candidate in [
                    Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
                    Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Docker" / "Docker" / "resources" / "docker.exe",
                    Path(r"C:\ProgramData\DockerDesktop\version-bin") / "docker.exe",
                    Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Ahmad Bin Haque\AppData\Local")) / "Microsoft" / "WindowsApps" / "docker.exe",
                ]:
                    if candidate.exists():
                        exe = str(candidate)
                        break
            DockerService._docker_exe = exe
        return DockerService._docker_exe

    @staticmethod
    def _wait_for_daemon(timeout: int = 20) -> bool:
        """Poll `docker info` until daemon is reachable or timeout."""
        exe = DockerService._find_docker()
        if not exe:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = subprocess.run([exe, "info"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return True
            time.sleep(1)
        return False

    @staticmethod
    def _diagnose(err: str) -> str:
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

    @staticmethod
    def _run(cmd: List[str], cwd: Optional[str] = None, timeout: int = 300) -> subprocess.CompletedProcess:
        docker = DockerService._find_docker()
        if docker is None:
            class _FakeResult:
                returncode = 1
                stdout = ""
                stderr = "Docker CLI not found in PATH. Please install Docker Desktop (Windows/Mac) or docker-ce (Linux) and add it to PATH."
            return _FakeResult()  # type: ignore[return-value]
        if cmd and cmd[0] == "docker":
            cmd[0] = docker
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 and r.stderr:
            r._dockliner_diag = DockerService._diagnose(r.stderr)  # type: ignore[attr-defined]
        return r

    @staticmethod
    def is_installed() -> bool:
        return DockerService._find_docker() is not None

    @staticmethod
    def is_running() -> bool:
        r = DockerService._run(["docker", "info"], timeout=5)
        return r.returncode == 0

    @staticmethod
    def installed_version() -> str:
        r = DockerService._run(["docker", "version", "--format", "{{.Client.Version}}"], timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""

    @staticmethod
    def start_daemon() -> tuple:
        if os.name == "nt":
            dd = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"
            if dd.exists():
                subprocess.Popen([str(dd)], shell=False)
                if DockerService._wait_for_daemon(timeout=30):
                    return (0, "Docker Desktop started")
            return (1, "Could not start Docker Desktop. Please start it manually from the system tray.")
        for cmd in [["sudo", "systemctl", "start", "docker"], ["sudo", "service", "docker", "start"]]:
            r = DockerService._run(cmd, timeout=15)
            if r.returncode == 0:
                return (0, "Docker daemon started")
        return (1, "Could not start Docker daemon. Start Docker Desktop or run: sudo systemctl start docker")

    @staticmethod
    def stop_daemon() -> tuple:
        if os.name == "nt":
            for ps_cmd in ["Start-Process -FilePath \"%ProgramFiles%\\Docker\\Docker\\Docker Desktop.exe\" -ArgumentList \"--quit\"", "Stop-Service com.docker.service"]:
                r = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    return (0, "Docker Desktop stopped")
            return (1, "Could not stop Docker Desktop automatically.")
        for cmd in [["sudo", "systemctl", "stop", "docker"], ["sudo", "service", "docker", "stop"]]:
            r = DockerService._run(cmd, timeout=15)
            if r.returncode == 0:
                return (0, "Docker daemon stopped")
        return (1, "Could not stop Docker daemon automatically.")

    @staticmethod
    def _with_preflight(cmd: List[str], cwd: Optional[str] = None, timeout: int = 300) -> subprocess.CompletedProcess:
        """Run a docker command after ensuring docker is installed and the daemon is reachable."""
        if not DockerService.is_installed():
            class _FakeResult:
                returncode = 1
                stdout = ""
                stderr = "Docker is not installed. Install Docker Desktop (Windows/Mac) or docker-ce (Linux) and restart DockLiner."
            return _FakeResult()  # type: ignore[return-value]
        if not DockerService.is_running():
            if not DockerService._wait_for_daemon(timeout=15):
                class _FakeResult:
                    returncode = 1
                    stdout = ""
                    stderr = "Docker daemon is not running. Start Docker Desktop (Windows/Mac) or run `sudo systemctl start docker` (Linux)."
                return _FakeResult()  # type: ignore[return-value]
        return DockerService._run(cmd, cwd=cwd, timeout=timeout)

    @staticmethod
    def run_shell_command(project_path: str, command: str) -> tuple:
        if not command.strip():
            return (1, "No direct command provided")
        r = DockerService._run(["bash", "-c", command], cwd=project_path)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def docker_build(project_path: str, image_name: str) -> tuple:
        cmd = ["docker", "build", "-t", image_name, "."]
        r = DockerService._with_preflight(cmd, cwd=project_path)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def run_image(image_name: str, port: int = 0) -> tuple:
        cmd = ["docker", "run", "-d", "--name", image_name, image_name]
        if port:
            cmd.extend(["-p", f"{port}:{port}"])
        r = DockerService._with_preflight(cmd)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def stop_container_by_project(name: str) -> tuple:
        cmd = ["docker", "stop", name]
        r = DockerService._with_preflight(cmd)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def container_logs_by_project(name: str, tail: int = 200) -> str:
        cmd = ["docker", "logs", "--tail", str(tail), name]
        r = DockerService._with_preflight(cmd)
        if r.returncode != 0:
            diag = getattr(r, "_dockliner_diag", r.stderr)
            return f"Docker error: {diag}"
        return r.stdout + r.stderr

    @staticmethod
    def compose_up(project_path: str, compose_file: str = "docker-compose.yml") -> tuple:
        cf = Path(project_path) / compose_file
        if not cf.exists():
            return (1, f"{compose_file} not found at {project_path}")
        cmd = ["docker", "compose", "-f", str(cf), "up", "-d", "--build"]
        r = DockerService._with_preflight(cmd, cwd=project_path)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def compose_build(project_path: str, compose_file: str = "docker-compose.yml") -> tuple:
        cf = Path(project_path) / compose_file
        if not cf.exists():
            return (1, f"{compose_file} not found at {project_path}")
        cmd = ["docker", "compose", "-f", str(cf), "build"]
        r = DockerService._with_preflight(cmd, cwd=project_path)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def compose_down(project_path: str, compose_file: str = "docker-compose.yml", remove_orphans: bool = True) -> tuple:
        cf = Path(project_path) / compose_file
        if not cf.exists():
            return (0, "no compose file")
        cmd = ["docker", "compose", "-f", str(cf), "down"]
        if remove_orphans:
            cmd.append("--remove-orphans")
        r = DockerService._with_preflight(cmd, cwd=project_path)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def compose_logs(project_path: str, compose_file: str = "docker-compose.yml", tail: int = 100) -> str:
        cf = Path(project_path) / compose_file
        if not cf.exists():
            return ""
        cmd = ["docker", "compose", "-f", str(cf), "logs", "--tail", str(tail)]
        r = DockerService._with_preflight(cmd, cwd=project_path)
        if r.returncode != 0:
            diag = getattr(r, "_dockliner_diag", r.stderr)
            return f"Docker error: {diag}"
        return r.stdout + r.stderr

    @staticmethod
    def system_prune() -> tuple:
        cmd = ["docker", "system", "prune", "-f"]
        r = DockerService._with_preflight(cmd)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def list_containers() -> List[Dict[str, Any]]:
        cache = DockerService._cache_get('list_containers')
        if cache is not None:
            return cache
        cmd = ["docker", "ps", "-a", "--format", "json"]
        r = DockerService._run(cmd, timeout=10)
        if r.returncode != 0:
            return []
        out = []
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        DockerService._cache_set('list_containers', out)
        return out

    @staticmethod
    def list_images() -> List[Dict[str, Any]]:
        cache = DockerService._cache_get('list_images')
        if cache is not None:
            return cache
        cmd = ["docker", "images", "--format", "json"]
        r = DockerService._run(cmd, timeout=10)
        if r.returncode != 0:
            return []
        out = []
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        DockerService._cache_set('list_images', out)
        return out

    @staticmethod
    def stop_container(container_id: str) -> tuple:
        cmd = ["docker", "stop", container_id]
        r = DockerService._with_preflight(cmd)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def remove_container(container_id: str, force: bool = False) -> tuple:
        cmd = ["docker", "rm", container_id]
        if force:
            cmd.append("-f")
        r = DockerService._with_preflight(cmd)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def remove_image(image_id: str, force: bool = False) -> tuple:
        cmd = ["docker", "rmi", image_id]
        if force:
            cmd.append("-f")
        r = DockerService._with_preflight(cmd)
        err = getattr(r, "_dockliner_diag", r.stderr)
        return (r.returncode, r.stdout + (err if r.returncode != 0 else ""))

    @staticmethod
    def list_networks() -> List[Dict[str, Any]]:
        cache = DockerService._cache_get('list_networks')
        if cache is not None:
            return cache
        cmd = ["docker", "network", "ls", "--format", "json"]
        r = DockerService._with_preflight(cmd)
        if r.returncode != 0:
            return []
        out = []
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        DockerService._cache_set('list_networks', out)
        return out

    @staticmethod
    def list_volumes() -> List[Dict[str, Any]]:
        cache = DockerService._cache_get('list_volumes')
        if cache is not None:
            return cache
        cmd = ["docker", "volume", "ls", "--format", "json"]
        r = DockerService._with_preflight(cmd)
        if r.returncode != 0:
            return []
        out = []
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        DockerService._cache_set('list_volumes', out)
        return out

    @staticmethod
    def inspect_container_ports(container_id: str) -> List[Dict[str, Any]]:
        cmd = ["docker", "inspect", "--format", "json", container_id]
        r = DockerService._with_preflight(cmd)
        if r.returncode != 0:
            return []
        ports = []
        if r.stdout.strip():
            try:
                data = json.loads(r.stdout.strip())
                if isinstance(data, list) and data:
                    network = data[0].get("NetworkSettings", {})
                    pm = network.get("Ports", {})
                    for container_port, bindings in pm.items():
                        if bindings:
                            for b in bindings:
                                ports.append({
                                    "container_port": container_port,
                                    "host_ip": b.get("HostIp", ""),
                                    "host_port": b.get("HostPort", "")
                                })
                        else:
                            ports.append({"container_port": container_port, "host_ip": "", "host_port": ""})
            except Exception:
                pass
        return ports

    @staticmethod
    def container_logs(cid: str, tail: int = 200) -> str:
        cmd = ["docker", "logs", "--tail", str(tail), cid]
        r = DockerService._with_preflight(cmd)
        if r.returncode != 0:
            diag = getattr(r, "_dockliner_diag", r.stderr)
            return f"Docker error: {diag}"
        return r.stdout + r.stderr

    @staticmethod
    def container_top(cid: str) -> Dict[str, Any]:
        cmd = ["docker", "top", cid]
        r = DockerService._with_preflight(cmd)
        if r.returncode != 0:
            return {"processes": [], "error": getattr(r, "_dockliner_diag", r.stderr)}
        lines = r.stdout.strip().splitlines()
        if lines:
            return {"processes": lines}
        return {"processes": [], "error": r.stderr}

    @staticmethod
    def container_resource_stats(project) -> Dict[str, Any]:
        """Return real container resource numbers with units (CPU%, RAM usage/limit, Block I/O, Net I/O, PIDs, Ports)."""
        from app.services.project_status_service import ProjectStatusService
        result: Dict[str, Any] = {"cpu": None, "ram": None, "ram_total": None, "disk": None, "net": None, "pids": None, "ports": []}
        state = ProjectStatusService.container_state(project)
        if not state["exists"] or state["state"] != "running":
            return result

        cid = state["container"].get("ID", "")
        all_stats = DockerService.system_stats()
        stats = next((s for s in all_stats if s.get("Container") == cid or s.get("ID") == cid), None)
        if not stats:
            return result

        result["cpu"] = stats.get("CPUPerc")
        mem_usage = stats.get("MemUsage") or ""
        if "/" in mem_usage:
            parts = mem_usage.split("/", 1)
            result["ram"] = parts[0].strip()
            result["ram_total"] = parts[1].strip()
        else:
            result["ram"] = mem_usage.strip()
        result["disk"] = stats.get("BlockIO")  # Docker format: "1.2MB / 0B"
        result["net"] = stats.get("NetIO")
        result["pids"] = stats.get("PIDs")
        result["ports"] = DockerService.container_ports_for_project(project)
        return result

    @staticmethod
    def container_ports_for_project(project) -> List[str]:
        """Return host→container port mappings for the project's running container."""
        from app.services.project_status_service import ProjectStatusService
        state = ProjectStatusService.container_state(project)
        if not state["exists"] or state["state"] != "running":
            return []
        cid = state["container"].get("ID", "")
        if not cid:
            return []
        return DockerService._format_port_mappings(DockerService.container_ports(cid))

    @staticmethod
    def _format_port_mappings(mappings: List[Dict[str, Any]]) -> List[str]:
        out = []
        for m in mappings:
            host = m.get("host_port") or ""
            container = m.get("container_port") or ""
            if host and container:
                out.append(f"{host}→{container}")
            elif container:
                out.append(container)
        return out

    @staticmethod
    def container_ports(cid: str) -> List[Dict[str, Any]]:
        cmd = ["docker", "inspect", "--format", "json", cid]
        r = DockerService._with_preflight(cmd)
        if r.returncode != 0:
            return []
        ports = []
        if r.stdout.strip():
            try:
                data = json.loads(r.stdout.strip())
                if isinstance(data, list) and data:
                    network = data[0].get("NetworkSettings", {})
                    pm = network.get("Ports", {})
                    for container_port, bindings in pm.items():
                        if bindings:
                            for b in bindings:
                                ports.append({
                                    "container_port": container_port,
                                    "host_ip": b.get("HostIp", ""),
                                    "host_port": b.get("HostPort", "")
                                })
                        else:
                            ports.append({"container_port": container_port, "host_ip": "", "host_port": ""})
            except Exception:
                pass
        return ports

    @staticmethod
    def system_stats() -> List[Dict[str, Any]]:
        cache = DockerService._cache_get('system_stats')
        if cache is not None:
            return cache
        cmd = ["docker", "stats", "--no-stream", "--format", "json"]
        r = DockerService._with_preflight(cmd)
        if r.returncode != 0:
            return []
        out = []
        if r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        DockerService._cache_set('system_stats', out)
        return out

    @staticmethod
    def security_summary() -> Dict[str, Any]:
        cmd = ["docker", "scout", "quickview"]
        r = DockerService._run(cmd, timeout=60)
        summary = {"docker_scout_available": r.returncode == 0, "output": r.stdout + r.stderr if r.returncode != 0 else ""}
        info = DockerService.docker_info()
        summary["live_restore"] = info.get("LiveRestoreEnabled", False)
        summary["userns_remap"] = info.get("UsernsRemap", "")
        summary["seccomp"] = bool(info.get("SecurityOptions", []))
        return summary

    @staticmethod
    def docker_info() -> Dict[str, Any]:
        cache = DockerService._cache_get('docker_info')
        if cache is not None:
            return cache
        cmd = ["docker", "info", "--format", "json"]
        r = DockerService._run(cmd)
        if r.returncode == 0 and r.stdout.strip():
            try:
                data = json.loads(r.stdout.strip())
                DockerService._cache_set('docker_info', data)
                return data
            except Exception:
                pass
        return {}

    @staticmethod
    def container_stats_for_project(project_path: str, compose_file: str = "docker-compose.yml") -> List[Dict[str, Any]]:
        proj_name = Path(project_path).name
        containers = DockerService.list_containers()
        related = [c for c in containers if proj_name.replace("-","_") in (c.get("Names") or "")]
        out = []
        all_stats = DockerService.system_stats()
        stat_map = {s.get("Container", s.get("ID", "")): s for s in all_stats}
        for c in related:
            cid = c.get("ID", "")
            out.append({"container": c, "stats": stat_map.get(cid, {})})
        return out

    @staticmethod
    def runtime_status() -> Dict[str, Any]:
        """Return a human-readable Docker runtime status summary."""
        return {
            "installed": DockerService.is_installed(),
            "running": DockerService.is_running(),
            "version": DockerService.installed_version(),
            "platform": os.name,
        }
