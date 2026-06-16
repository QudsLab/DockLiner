import os, subprocess, shutil, json, re
from pathlib import Path
from typing import List, Dict, Any, Optional
from app.core.config import settings

class DockerService:
    @staticmethod
    def _run(cmd: List[str], cwd: Optional[str] = None, timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)

    @staticmethod
    def is_installed() -> bool:
        """Check if docker CLI exists in PATH"""
        return shutil.which("docker") is not None

    @staticmethod
    def is_running() -> bool:
        """Check if docker daemon is reachable"""
        r = DockerService._run(["docker", "info"], timeout=5)
        return r.returncode == 0

    @staticmethod
    def installed_version() -> str:
        """Return docker client version or empty string"""
        r = DockerService._run(["docker", "version", "--format", "{{.Client.Version}}"], timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""

    @staticmethod
    def start_daemon() -> tuple:
        for cmd in [["sudo", "systemctl", "start", "docker"], ["sudo", "service", "docker", "start"]]:
            r = DockerService._run(cmd, timeout=15)
            if r.returncode == 0:
                return (0, "Docker daemon started")
        return (1, "Could not start Docker daemon. Start Docker Desktop or run: sudo systemctl start docker")

    @staticmethod
    def stop_daemon() -> tuple:
        for cmd in [["sudo", "systemctl", "stop", "docker"], ["sudo", "service", "docker", "stop"]]:
            r = DockerService._run(cmd, timeout=15)
            if r.returncode == 0:
                return (0, "Docker daemon stopped")
        return (1, "Could not stop Docker daemon automatically.")

    @staticmethod
    def docker_build(project_path: str, image_name: str) -> tuple:
        cmd = ["docker", "build", "-t", image_name, "."]
        r = DockerService._run(cmd, cwd=project_path)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def run_image(image_name: str, port: int) -> tuple:
        cmd = ["docker", "run", "-d", "--name", image_name, "-p", f"{port}:{port}", image_name]
        r = DockerService._run(cmd)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def stop_container_by_project(name: str) -> tuple:
        cmd = ["docker", "stop", name]
        r = DockerService._run(cmd)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def container_logs_by_project(name: str, tail: int = 200) -> str:
        cmd = ["docker", "logs", "--tail", str(tail), name]
        r = DockerService._run(cmd)
        return r.stdout + r.stderr

    @staticmethod
    def compose_up(project_path: str, compose_file: str = "docker-compose.yml") -> tuple:
        cf = Path(project_path) / compose_file
        if not cf.exists():
            return (1, f"{compose_file} not found at {project_path}")
        cmd = ["docker", "compose", "-f", str(cf), "up", "-d", "--build"]
        r = DockerService._run(cmd, cwd=project_path)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def compose_down(project_path: str, compose_file: str = "docker-compose.yml", remove_orphans: bool = True) -> tuple:
        cf = Path(project_path) / compose_file
        if not cf.exists():
            return (0, "no compose file")
        cmd = ["docker", "compose", "-f", str(cf), "down"]
        if remove_orphans:
            cmd.append("--remove-orphans")
        r = DockerService._run(cmd, cwd=project_path)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def compose_logs(project_path: str, compose_file: str = "docker-compose.yml", tail: int = 100) -> str:
        cf = Path(project_path) / compose_file
        if not cf.exists():
            return ""
        cmd = ["docker", "compose", "-f", str(cf), "logs", "--tail", str(tail)]
        r = DockerService._run(cmd, cwd=project_path)
        return r.stdout + r.stderr

    @staticmethod
    def system_prune() -> tuple:
        cmd = ["docker", "system", "prune", "-f"]
        r = DockerService._run(cmd)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def list_containers() -> List[Dict[str, Any]]:
        cmd = ["docker", "ps", "-a", "--format", "json"]
        r = DockerService._run(cmd)
        out = []
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        return out

    @staticmethod
    def list_images() -> List[Dict[str, Any]]:
        cmd = ["docker", "images", "--format", "json"]
        r = DockerService._run(cmd)
        out = []
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        return out

    @staticmethod
    def stop_container(container_id: str) -> tuple:
        cmd = ["docker", "stop", container_id]
        r = DockerService._run(cmd)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def remove_container(container_id: str, force: bool = False) -> tuple:
        cmd = ["docker", "rm", container_id]
        if force:
            cmd.append("-f")
        r = DockerService._run(cmd)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def remove_image(image_id: str, force: bool = False) -> tuple:
        cmd = ["docker", "rmi", image_id]
        if force:
            cmd.append("-f")
        r = DockerService._run(cmd)
        return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def list_networks() -> List[Dict[str, Any]]:
        cmd = ["docker", "network", "ls", "--format", "json"]
        r = DockerService._run(cmd)
        out = []
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        return out

    @staticmethod
    def list_volumes() -> List[Dict[str, Any]]:
        cmd = ["docker", "volume", "ls", "--format", "json"]
        r = DockerService._run(cmd)
        out = []
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        return out

    @staticmethod
    def rsync_delete(src: str, dst: str) -> tuple:
        if os.name == "nt":
            # Windows fallback: remove dst contents then copy
            dst_path = Path(dst)
            if dst_path.exists():
                for item in dst_path.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
            for item in Path(src).iterdir():
                s = str(item)
                d = str(dst_path / item.name)
                if item.is_dir():
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
            return (0, "synced (windows fallback)")
        else:
            cmd = ["rsync", "-a", "--delete", f"{src}/", f"{dst}/"]
            r = DockerService._run(cmd)
            return (r.returncode, r.stdout + r.stderr)

    @staticmethod
    def inspect_container_ports(container_id: str) -> List[Dict[str, Any]]:
        cmd = ["docker", "inspect", "--format", "json", container_id]
        r = DockerService._run(cmd)
        ports = []
        if r.returncode == 0 and r.stdout.strip():
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
        r = DockerService._run(cmd)
        return r.stdout + r.stderr

    @staticmethod
    def container_top(cid: str) -> Dict[str, Any]:
        cmd = ["docker", "top", cid]
        r = DockerService._run(cmd)
        if r.returncode == 0:
            lines = r.stdout.strip().splitlines()
            if lines:
                return {"processes": lines}
        return {"processes": [], "error": r.stderr}

    @staticmethod
    def system_stats() -> List[Dict[str, Any]]:
        cmd = ["docker", "stats", "--no-stream", "--format", "json"]
        r = DockerService._run(cmd)
        out = []
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        return out

    @staticmethod
    def security_summary() -> Dict[str, Any]:
        # Try docker scout if available
        cmd = ["docker", "scout", "quickview"]
        r = DockerService._run(cmd, timeout=60)
        summary = {"docker_scout_available": r.returncode == 0, "output": r.stdout + r.stderr if r.returncode != 0 else ""}
        # Also basic daemon security info
        info = DockerService.docker_info()
        summary["live_restore"] = info.get("LiveRestoreEnabled", False)
        summary["userns_remap"] = info.get("UsernsRemap", "")
        summary["seccomp"] = bool(info.get("SecurityOptions", []))
        return summary

    @staticmethod
    def docker_info() -> Dict[str, Any]:
        cmd = ["docker", "info", "--format", "json"]
        r = DockerService._run(cmd)
        if r.returncode == 0 and r.stdout.strip():
            try:
                return json.loads(r.stdout.strip())
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
