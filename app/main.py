from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.core.db import init_db
from app.routers import api, pages

def create_app() -> FastAPI:
    app = FastAPI(title="DockLiner", version="0.1.0")
    init_db()
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(pages.router)
    app.include_router(api.router)
    return app