"""Authentication endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.rate_limit import check_rate, client_ip
from app.database.session import get_db
from app.models import User
from app.schemas.requests import (ChangePasswordIn, ForgotPasswordIn, LoginIn, LogoutIn, ProfileIn, RefreshIn, RegisterIn,
                                  ResetPasswordIn, TokenIn)
from app.services import audit, auth_service

router = APIRouter(tags=["auth"])


def _limit(request: Request, action: str) -> str:
    ip = client_ip(request)
    check_rate(f"{action}:{ip}", get_settings().RATE_LIMIT_AUTH_PER_MINUTE)
    return ip


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    ip = _limit(request, "register")
    user = auth_service.register(db, body.model_dump(), ip)
    return {"user": user.to_dict(), "message": "Account created. Check your e-mail for a verification link, then sign in."}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = _limit(request, "login")
    return auth_service.login(db, body.email, body.password, request.headers.get("user-agent"), ip)


@router.post("/auth/refresh")
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    ip = _limit(request, "refresh")
    return auth_service.refresh(db, body.refresh_token, request.headers.get("user-agent"), ip)


@router.post("/auth/logout")
def logout(body: LogoutIn | None = None, everywhere: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service.logout(db, user, body.refresh_token if body else None, everywhere)
    return {"message": "Signed out."}


@router.post("/auth/forgot-password")
def forgot_password(body: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    ip = _limit(request, "forgot")
    auth_service.forgot_password(db, body.email, ip)
    return {"message": "If an account exists for that address, a password-reset link has been sent."}


@router.post("/auth/reset-password")
def reset_password(body: ResetPasswordIn, request: Request, db: Session = Depends(get_db)):
    ip = _limit(request, "reset")
    auth_service.reset_password(db, body.token, body.new_password, ip)
    return {"message": "Your password has been changed. Sign in with the new password."}


@router.post("/auth/verify-email")
def verify_email(body: TokenIn, request: Request, db: Session = Depends(get_db)):
    _limit(request, "verify")
    user = auth_service.verify_email(db, body.token)
    return {"message": "E-mail address verified.", "user": user.to_dict()}


@router.post("/auth/resend-verification")
def resend_verification(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _limit(request, "verify")
    auth_service.resend_verification(db, user)
    return {"message": "Verification e-mail sent."}


@router.get("/auth/sessions")
def sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"sessions": [s.to_dict() for s in auth_service.active_sessions(db, user.id)]}


@router.get("/users/me")
def me(user: User = Depends(get_current_user)):
    return user.to_dict()


@router.put("/users/me")
def update_me(body: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "full_name" and not value:
            continue
        setattr(user, field, value)
    audit.record(db, action="user.profile_updated", user_id=user.id, entity_type="user", entity_id=user.id)
    db.commit()
    return user.to_dict()


@router.put("/users/me/password")
def change_password(body: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    auth_service.change_password(db, user, body.current_password, body.new_password)
    return {"message": "Password changed. Sign in again on your other devices."}
