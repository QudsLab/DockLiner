from urllib.request import Request, urlopen
import json
from app.core.config import settings

class VersionService:
    @staticmethod
    def check() -> dict:
        current = settings.VERSION
        latest = current
        url = "https://api.github.com/repos/QudsLab/DockLiner/releases/latest"
        try:
            req = Request(url, headers={"User-Agent": "DockLiner"}, method="GET")
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latest = data.get("tag_name", current).lstrip("v")
        except Exception:
            pass
        return {
            "current": current,
            "latest": latest,
            "has_update": latest != current and latest != "0.0.0",
            "update_available": latest != current and latest != "0.0.0",
            "url": data.get("html_url") if 'data' in dir() and isinstance(data, dict) else None,
        }
