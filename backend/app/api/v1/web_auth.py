"""
Authentication for the web app: an httpOnly, SameSite=Lax cookie holding a
7-day JWT. JavaScript cannot read it, and the app and API share one origin.
API clients can keep using /auth/login and a Bearer token.
"""
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.api.deps import AUTH_COOKIE, get_current_active_user
from app.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User

router = APIRouter()
COOKIE_DAYS = 7


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    invite_code: Optional[str] = None


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name,
            "invite_required": bool(settings.INVITE_CODE)}


def _set_cookie(request: Request, response: Response, user: User) -> None:
    token = create_access_token({"sub": user.email}, expires_delta=timedelta(days=COOKIE_DAYS))
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(AUTH_COOKIE, token, max_age=COOKIE_DAYS * 86400, httponly=True,
                        samesite="lax", secure=secure, path="/")


@router.get("/config")
def config():
    """Public settings the sign-in page needs."""
    return {"invite_required": bool(settings.INVITE_CODE), "app_name": settings.APP_NAME}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: DBSession = Depends(get_db)):
    u = db.query(User).filter(func.lower(User.email) == body.email.lower()).first()
    if not u or not u.is_active or not verify_password(body.password, u.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    _set_cookie(request, response, u)
    return user_out(u)


@router.post("/register", status_code=201)
def register(body: RegisterBody, request: Request, response: Response, db: DBSession = Depends(get_db)):
    if settings.INVITE_CODE and not secrets.compare_digest((body.invite_code or "").strip(), settings.INVITE_CODE):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That invite code is not valid")
    email = body.email.lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An account with that email already exists")
    u = User(email=email, full_name=(body.full_name or "").strip() or None,
             hashed_password=get_password_hash(body.password))
    db.add(u)
    db.commit()
    _set_cookie(request, response, u)
    return user_out(u)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(AUTH_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(current_user: User = Depends(get_current_active_user)):
    return user_out(current_user)
