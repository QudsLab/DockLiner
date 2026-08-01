import subprocess
from typing import Dict, Any, Optional

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


class SystemResourcesService:
    @staticmethod
    def get() -> Dict[str, Optional[float]]:
        data: Dict[str, Optional[float]] = {"cpu": None, "ram": None, "disk": None, "gpu": None}
        if not psutil:
            return data

        try:
            data["cpu"] = psutil.cpu_percent(interval=0.1)
        except Exception:
            pass

        try:
            data["ram"] = psutil.virtual_memory().percent
        except Exception:
            pass

        import os
        try:
            disk_path = "C:\\" if os.name == "nt" else "/"
            data["disk"] = psutil.disk_usage(disk_path).percent
        except Exception:
            pass

        try:
            data["gpu"] = SystemResourcesService._gpu_util()
        except Exception:
            pass

        return data

    @staticmethod
    def _gpu_util() -> Optional[float]:
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                vals = [float(x.strip()) for x in r.stdout.strip().splitlines() if x.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass
        return None
