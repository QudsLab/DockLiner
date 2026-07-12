from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

def _build_database_url():
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    db_type = settings.DB_TYPE.lower()
    if db_type == "sqlite":
        return f"sqlite:///{settings.DB_PATH}"
    if db_type == "mysql":
        driver = (settings.DB_DRIVER if settings.DB_DRIVER and "mysql" in settings.DB_DRIVER else "pymysql")
        port = settings.DB_PORT or 3306
        return f"mysql+{driver}://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{port}/{settings.DB_NAME}"
    if db_type in ("postgres", "postgresql"):
        driver = (settings.DB_DRIVER if settings.DB_DRIVER and "psycopg" in settings.DB_DRIVER else "psycopg2")
        port = settings.DB_PORT or 5432
        return f"postgresql+{driver}://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{port}/{settings.DB_NAME}"
    raise ValueError(f"Unsupported DB_TYPE: {settings.DB_TYPE}")

DATABASE_URL = _build_database_url()

engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

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
    MigrationService.auto_init_blank(Base)
