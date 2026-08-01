from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings, build_database_url, resolve_db_mode

DATABASE_URL = build_database_url()
MODE = resolve_db_mode()

engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# Module-level pending migration ops. Populated by init_db() if schema drift is detected.
PENDING_MIGRATION_OPS = []

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # Import all models so they register with Base metadata before create_all
    from app.models.project import Project, Deployment, AccessToken, HealthCheck, Metric, AuditLog, Webhook, Notification, GithubCache, SavedOrg, Download, ErrorLog  # noqa
    # Only auto-init a completely blank DB; migrations handle existing DB drift.
    from app.services.migration_service import MigrationService
    global PENDING_MIGRATION_OPS
    PENDING_MIGRATION_OPS.clear()
    if MigrationService.auto_init_blank(Base):
        return
    PENDING_MIGRATION_OPS.extend(MigrationService.diff_schema(Base))
