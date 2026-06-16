from pathlib import Path
from urllib.request import Request, urlopen
import json
from app.core.config import settings

class VersionService:
    @staticmethod
    def _version_file() -> str:
        root = Path(__file__).resolve().parent.parent.parent
        vf = root / "VERSION"
        if vf.exists():
            return vf.read_text(encoding="utf-8").strip()
        return "0.2.0"

    @staticmethod
    def check() -> dict:
        current = VersionService._version_file()
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
            "update_available": latest != current and latest != "0.0.0",
        }
