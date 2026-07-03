from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.core.config import settings
from app.core.db import init_db
from app.core.error_middleware import ErrorLogMiddleware
from app.routers import api, pages
from app.services.dockliner_service import DockLinerService

def create_app() -> FastAPI:
    app = FastAPI(title="DockLiner", version="0.1.0")
    init_db()
    DockLinerService.ensure_dirs()
    app.add_middleware(ErrorLogMiddleware)
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(pages.router)
    app.include_router(api.router)
    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True, log_level="info")
