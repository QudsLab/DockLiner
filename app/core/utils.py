import socket
from typing import List, Optional
from app.core.config import settings

def find_free_ports(start: int = None, count: int = 1) -> List[int]:
    """Return `count` free ports starting from `start` if given, otherwise
    from the configured DOCKLINER_ALLOWED_PORTS whitelist.
    """
    candidates = []
    if start is not None:
        candidates = list(range(start, 65000))
    else:
        # Use the configured allowed port whitelist (50xxx primes by default).
        raw = (settings.ALLOWED_PORTS or "50021,50023,50033,50047,50051,50053,50069,50077,50087,50093,50101,50111,50119,50123")
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                candidates.append(int(part))
    found = []
    for port in candidates:
        if len(found) >= count:
            break
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            found.append(port)
        except OSError:
            pass
        finally:
            s.close()
    return found

def is_port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()
