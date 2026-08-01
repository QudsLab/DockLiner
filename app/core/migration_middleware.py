from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, HTMLResponse
from app.core.db import PENDING_MIGRATION_OPS
from app.core.auth import get_session_user

class MigrationMiddleware(BaseHTTPMiddleware):
    """Redirect root to migration page when schema drift is detected.
    Block everyone else until migrations are applied.
    """
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Always allow these paths so the migration page and login work.
        allow = (
            path.startswith("/static/") or
            path in ("/login", "/api/login", "/logout", "/api/logout", "/migration") or
            path.startswith("/api/migration/")
        )
        if allow or not PENDING_MIGRATION_OPS:
            return await call_next(request)

        user = get_session_user(request)
        if not user:
            # Unauthenticated users must reach /login normally; let auth layer handle it.
            return await call_next(request)
        if user == "root":
            if path != "/migration":
                return RedirectResponse(url="/migration", status_code=307)
            return await call_next(request)

        # Non-root authenticated users see maintenance.
        return HTMLResponse(
            content="""<!doctype html>
<html>
<head><title>Maintenance — DockLiner</title>
<style>
body{background:#0f172a;color:#e2e8f0;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
.card{max-width:420px;padding:32px;border:1px solid #334155;border-radius:16px;background:#1e293b}
h1{margin:0 0 12px;color:#ff7300}
p{margin:0;color:#94a3b8;line-height:1.5}
</style>
</head>
<body>
  <div class="card">
    <h1>DockLiner Maintenance</h1>
    <p>The database needs a schema migration. Only the root user can apply it.<br>Please ask the administrator to log in and run the migration.</p>
  </div>
</body>
</html>""",
            status_code=503,
        )
