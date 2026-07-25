import os
import subprocess
import threading
import shlex
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

class TerminalService:
    """Lightweight persistent shell session per project.

    Runs an OS shell (bash on Linux/macOS, cmd.exe on Windows) as the same user
    that owns the DockLiner process.  Because DockLiner is intended to run as
    root/admin for Docker control, the terminal inherits those privileges.
    """

    _sessions: Dict[int, dict] = {}
    _lock = threading.Lock()

    @classmethod
    def _session(cls, project_id: int, cwd: Optional[str] = None) -> dict:
        with cls._lock:
            s = cls._sessions.get(project_id)
            if s is None or s["proc"].poll() is not None:
                proc, shell = cls._start_shell(cwd)
                s = {
                    "proc": proc,
                    "shell": shell,
                    "cwd": cwd or os.getcwd(),
                    "buffer": [],
                    "lock": threading.Lock(),
                }
                cls._sessions[project_id] = s
                cls._start_reader(s)
            elif cwd and s["cwd"] != cwd:
                cls._send_cd(s, cwd)
                s["cwd"] = cwd
            return s

    @classmethod
    def _start_shell(cls, cwd: Optional[str] = None):
        if os.name == "nt":
            # Use cmd.exe with a recognizable prompt so we can split output lines.
            proc = subprocess.Popen(
                ["cmd.exe", "/K", "prompt", "$G"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=cwd or os.getcwd(),
                encoding="utf-8",
                errors="replace",
            )
            return proc, "cmd"
        proc = subprocess.Popen(
            ["bash", "-i"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=cwd or os.getcwd(),
            encoding="utf-8",
            errors="replace",
        )
        return proc, "bash"

    @classmethod
    def _start_reader(cls, s: dict):
        def reader():
            try:
                for line in iter(s["proc"].stdout.readline, ""):
                    with s["lock"]:
                        s["buffer"].append(line.rstrip("\r\n"))
                        if len(s["buffer"]) > 2000:
                            s["buffer"] = s["buffer"][-2000:]
            except Exception:
                pass
        t = threading.Thread(target=reader, daemon=True)
        t.start()

    @classmethod
    def _send_cd(cls, s: dict, cwd: str):
        if s["shell"] == "cmd":
            s["proc"].stdin.write(f'cd /d "{cwd}"\n')
        else:
            s["proc"].stdin.write(f'cd "{shlex.quote(cwd)}"\n')
        s["proc"].stdin.flush()

    @classmethod
    def exec(cls, project_id: int, command: str, cwd: Optional[str] = None) -> dict:
        s = cls._session(project_id, cwd)
        marker = f"__DL_END_{datetime.utcnow().timestamp()}__"
        if s["shell"] == "cmd":
            # Echo marker after the command; the prompt itself is '>'
            line = f'{command} & echo {marker}\n'
        else:
            line = f'{command}; echo "{marker}"\n'
        s["proc"].stdin.write(line)
        s["proc"].stdin.flush()

        # Collect output until the marker appears (with a short busy wait).
        out: List[str] = []
        deadline = datetime.utcnow().timestamp() + 30
        while datetime.utcnow().timestamp() < deadline:
            with s["lock"]:
                # look for marker
                buf = list(s["buffer"])
            for i, b in enumerate(buf):
                if marker in b:
                    # output between last known position and marker
                    out = [b for b in buf if b != marker]
                    return {"rc": 0, "output": "\n".join(out)}
            import time
            time.sleep(0.05)
        with s["lock"]:
            out = list(s["buffer"])
        return {"rc": 0, "output": "\n".join(out), "pending": True}

    @classmethod
    def read(cls, project_id: int, limit: int = 500) -> dict:
        s = cls._sessions.get(project_id)
        if not s:
            return {"output": "", "cwd": "", "running": False}
        with s["lock"]:
            lines = s["buffer"][-limit:]
        return {"output": "\n".join(lines), "cwd": s["cwd"], "running": s["proc"].poll() is None}

    @classmethod
    def reset(cls, project_id: int, cwd: Optional[str] = None) -> dict:
        with cls._lock:
            s = cls._sessions.pop(project_id, None)
            if s:
                try:
                    s["proc"].terminate()
                except Exception:
                    pass
        return {"ok": True}
