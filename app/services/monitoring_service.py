import datetime, json, sqlite3, subprocess, re, socket
from typing import Dict, Any, Optional, List
from app.core.config import settings
from app.services.docker_service import DockerService

class MonitoringService:
    @staticmethod
    def run_health_check(check: Dict[str, Any]) -> Dict[str, Any]:
        protocol = check.get("protocol", "http")
        host = check.get("host", "localhost")
        port = check.get("port")
        path = check.get("path", "/")
        if not port:
            return {"status": "down", "latency_ms": None, "error": "no port"}
        try:
            if protocol == "tcp":
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5)
                t0 = datetime.datetime.utcnow()
                s.connect((host, int(port)))
                t1 = datetime.datetime.utcnow()
                s.close()
                latency = int((t1 - t0).total_seconds() * 1000)
                return {"status": "up", "latency_ms": latency, "error": None}
            else:
                import urllib.request
                url = f"http://{host}:{port}{path}"
                t0 = datetime.datetime.utcnow()
                req = urllib.request.urlopen(url, timeout=5)
                code = req.status
                t1 = datetime.datetime.utcnow()
                latency = int((t1 - t0).total_seconds() * 1000)
                return {"status": "up" if 200 <= code < 400 else "down", "latency_ms": latency, "error": None}
        except Exception as e:
            return {"status": "down", "latency_ms": None, "error": str(e)}

    @staticmethod
    def poll_all_health(db) -> List[Dict[str, Any]]:
        # db session passed
        from app.models.project import HealthCheck
        checks = db.query(HealthCheck).filter(HealthCheck.enabled == True).all()
        results = []
        for c in checks:
            r = MonitoringService.run_health_check({"protocol": c.protocol, "host": c.host, "port": c.port, "path": c.path})
            c.last_check = datetime.datetime.utcnow()
            c.last_status = r["status"]
            c.last_latency_ms = r["latency_ms"]
            results.append({"project_id": c.project_id, "status": r["status"], "latency_ms": r["latency_ms"], "error": r["error"]})
        db.commit()
        return results

    @staticmethod
    def record_docker_stats(db) -> None:
        from app.models.project import Metric, Project
        stats = DockerService.system_stats()
        # Map containers to projects by name heuristic
        projects = {p.name: p.id for p in db.query(Project).all()}
        for s in stats:
            cid = s.get("Container", s.get("ID", ""))
            cname = s.get("Name", "")
            pid = None
            for pname, p_id in projects.items():
                if pname in cname:
                    pid = p_id
                    break
            for mtype, key in [("cpu_percent", "CPUPerc"), ("mem_percent", "MemPerc"), ("mem_usage", "MemUsage"), ("net_io", "NetIO"), ("block_io", "BlockIO")]:
                val = s.get(key, "")
                if val:
                    db.add(Metric(project_id=pid, container_id=cid, container_name=cname, metric_type=mtype, value=str(val)))
        # Prune old metrics older than 6 hours
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=6)
        db.query(Metric).filter(Metric.recorded_at < cutoff).delete(synchronize_session=False)
        db.commit()

    @staticmethod
    def get_project_metrics(db, project_id: int, metric_type: str, limit: int = 100) -> List[Dict[str, Any]]:
        from app.models.project import Metric
        rows = db.query(Metric).filter(Metric.project_id == project_id, Metric.metric_type == metric_type).order_by(Metric.recorded_at.desc()).limit(limit).all()
        return [{"value": r.value, "recorded_at": r.recorded_at.isoformat()} for r in reversed(rows)]

    @staticmethod
    def send_webhook(webhook_url: str, event: str, payload: Dict[str, Any]) -> bool:
        try:
            import urllib.request
            data = json.dumps({"event": event, "payload": payload, "timestamp": datetime.datetime.utcnow().isoformat()}).encode("utf-8")
            req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception:
            return False

class AuditService:
    @staticmethod
    def log(db, action: str, target: str = "", details: str = "", user: str = "", ip: str = "", user_agent: str = "") -> None:
        from app.models.project import AuditLog
        db.add(AuditLog(user=user, action=action, target=target, ip=ip, user_agent=user_agent, details=details))
        db.commit()

class RateLimitService:
    # In-memory simple rate limiter; for single-process this is fine
    buckets: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def check(key: str, max_requests: int, window_seconds: int) -> bool:
        now = datetime.datetime.utcnow()
        bucket = RateLimitService.buckets.get(key, {"count": 0, "reset": now})
        if now >= bucket["reset"]:
            bucket = {"count": 0, "reset": now + datetime.timedelta(seconds=window_seconds)}
        bucket["count"] += 1
        RateLimitService.buckets[key] = bucket
        return bucket["count"] <= max_requests

    @staticmethod
    def limit_login(ip: str) -> bool:
        return RateLimitService.check(f"login:{ip}", 5, 60)

    @staticmethod
    def limit_deploy(project_id: int, ip: str) -> bool:
        return RateLimitService.check(f"deploy:{project_id}:{ip}", 3, 60)
