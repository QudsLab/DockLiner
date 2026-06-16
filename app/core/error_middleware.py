import traceback
import datetime
from fastapi import Request
from sqlalchemy.orm import Session
from app.services.error_log_service import ErrorLogService
from app.core.auth import get_session_user

class ErrorLogMiddleware:
    """Logs unhandled Python exceptions to the DB."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)

        async def wrapped_send(message):
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except Exception as exc:
            try:
                db = next(_db_gen())
                user = get_session_user(request)
                ErrorLogService.log_exception(
                    db,
                    exc,
                    source="python",
                    url=str(request.url),
                    user=user,
                    user_agent=request.headers.get("user-agent", "")[:500],
                )
                db.close()
            except Exception:
                pass
            raise

def _db_gen():
    from app.core.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
