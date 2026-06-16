import socket
from typing import List, Optional

def find_free_ports(start: int = 25600, count: int = 2) -> List[int]:
    found = []
    port = start
    while len(found) < count and port < 65000:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            found.append(port)
        except OSError:
            pass
        finally:
            s.close()
        port += 1
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
