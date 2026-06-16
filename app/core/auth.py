import os, json
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from blake3 import blake3
from app.core.config import ALLOWED_USERS

def hash_pass(password: str) -> str:
    return blake3(password.encode("utf-8")).hexdigest(length=64)

def verify(user: str, password: str) -> bool:
    h = hash_pass(password)
    for entry in ALLOWED_USERS:
        if entry.get("user") == user and entry.get("hash") == h:
            return True
    return False

def get_session_user(request: Request) -> str:
    return request.cookies.get("dockliner_user", "")

def require_auth(request: Request):
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=307, headers={"Location":"/login"}, detail="Not authenticated")
    return user

def login_user(user: str) -> dict:
    return {"dockliner_user": user, "dockliner_login": str(datetime.utcnow())}

def logout_user() -> dict:
    return {"dockliner_user": "", "dockliner_login": ""}
