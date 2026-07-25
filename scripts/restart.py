import os
import sys
import time
import subprocess
import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWN_PID = int(sys.argv[1]) if len(sys.argv) > 1 else os.getpid()

time.sleep(1)

for p in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd']):
    try:
        if p.info['pid'] == OWN_PID:
            continue
        cmd = ' '.join(p.info.get('cmdline') or [])
        cwd = p.info.get('cwd') or ''
        if (p.info['name'] in ('python.exe', 'pythonw.exe', 'python')
                and (ROOT in cwd or 'main.py' in cmd or 'DockLiner' in cwd)):
            try:
                psutil.Process(p.info['pid']).kill()
            except Exception:
                pass
    except Exception:
        pass

subprocess.Popen(
    [sys.executable, os.path.join(ROOT, 'main.py')],
    cwd=ROOT,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
    creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0) if os.name == 'nt' else 0,
)
