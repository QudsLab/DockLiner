"""Central log capture service. Stores every Docker/system event in system_logs."""
from sqlalchemy.orm import Session
from app.core.db import SessionLocal
from app.models.project import SystemLog
from datetime import datetime
from typing import Optional, Dict, Any
import traceback

class LogService:

    @classmethod
    def _session(cls) -> Session:
        return SessionLocal()

    @classmethod
    def add(cls, source: str, message: str, level: str = "info", details: str = "", project_id: Optional[int] = None):
        """Persist one event. source in: docker|system|deploy|daemon|preflight."""
        db = cls._session()
        try:
            log = SystemLog(
                source=source,
                level=level,
                message=message,
                details=details,
                project_id=project_id,
                created_at=datetime.utcnow(),
            )
            db.add(log)
            db.commit()
        finally:
            db.close()

    @classmethod
    def docker_result(cls, operation: str, rc: int, stdout: str, stderr: str = "", project_id: Optional[int] = None):
        level = "error" if rc != 0 else "info"
        msg = f"docker {operation}: {'OK' if rc == 0 else 'FAILED'}"
        details = (stderr or stdout or "")[:4000]
        cls.add("docker", msg, level, details, project_id)

    @classmethod
    def daemon(cls, action: str, rc: int, output: str):
        level = "error" if rc != 0 else "info"
        cls.add("daemon", f"daemon {action}: {'OK' if rc == 0 else 'FAILED'}", level, output[:4000])

    @classmethod
    def preflight(cls, check: str, passed: bool, detail: str = ""):
        level = "error" if not passed else "info"
        cls.add("system", f"preflight {check}: {'OK' if passed else 'FAILED'}", level, detail)

    @classmethod
    def deploy(cls, project_id: int, project_name: str, status: str, output: str = ""):
        level = "error" if status == "error" else "info"
        cls.add("deploy", f"deploy {project_name}: {status}", level, output[:4000], project_id)

    @classmethod
    def error(cls, source: str, exc: Exception, details: Dict[str, Any] = None):
        details_str = ""
        if details:
            try:
                import json
                details_str = json.dumps(details, default=str)
            except Exception:
                details_str = str(details)
        cls.add(source, f"{source} error: {type(exc).__name__}: {exc}", "error", details_str + "\n" + traceback.format_exc())

    @classmethod
    def grouped_by_day(cls, limit_days: int = 30, project_id: Optional[int] = None, source: Optional[str] = None):
        """Return { 'YYYY-MM-DD': [log dicts, ...], ... } for the last N days."""
        db = cls._session()
        try:
            q = db.query(SystemLog)
            if project_id is not None:
                q = q.filter(SystemLog.project_id == project_id)
            if source:
                q = q.filter(SystemLog.source == source)
            from datetime import timedelta
            since = datetime.utcnow() - timedelta(days=limit_days)
            q = q.filter(SystemLog.created_at >= since)
            logs = q.order_by(SystemLog.created_at.desc()).all()
            out: Dict[str, list] = {}
            for log in logs:
                day = (log.created_at or datetime.utcnow()).strftime("%Y-%m-%d")
                out.setdefault(day, []).append(log.to_dict())
            return out
        finally:
            db.close()
