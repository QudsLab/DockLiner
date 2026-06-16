from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

engine = create_engine(f"sqlite:///{settings.DB_PATH}", connect_args={"check_same_thread": False})
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
    from app.models.project import Project, Deployment, AccessToken, HealthCheck, Metric, AuditLog, Webhook, Notification, GithubCache, SavedOrg  # noqa
    Base.metadata.create_all(bind=engine)
