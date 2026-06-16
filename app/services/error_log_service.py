import traceback
import datetime
from sqlalchemy.orm import Session
from app.models.project import ErrorLog

class ErrorLogService:
    @staticmethod
    def log(db: Session, source: str, message: str, level: str = "error", stack: str = "", url: str | None = None, user: str | None = None, user_agent: str | None = None) -> ErrorLog:
        entry = ErrorLog(
            source=source,
            level=level,
            message=str(message)[:4000],
            stack=str(stack)[:8000],
            url=str(url)[:500] if url else None,
            user=str(user)[:100] if user else None,
            user_agent=str(user_agent)[:500] if user_agent else None,
            created_at=datetime.datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    @staticmethod
    def log_exception(db: Session, exc: Exception, source: str = "python", url: str | None = None, user: str | None = None, user_agent: str | None = None) -> ErrorLog:
        return ErrorLogService.log(
            db=db,
            source=source,
            message=str(exc),
            level="error",
            stack="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            url=url,
            user=user,
            user_agent=user_agent,
        )

    @staticmethod
    def list(db: Session, limit: int = 100, source: str = None) -> list:
        q = db.query(ErrorLog)
        if source:
            q = q.filter(ErrorLog.source == source)
        return q.order_by(ErrorLog.created_at.desc()).limit(limit).all()
