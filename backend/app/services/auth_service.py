"""Accounts and sessions: registration, login, refresh-token rotation,
logout, password reset and e-mail verification."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiError, bad_request
from app.core.security import (create_access_token, hash_password, hash_token, needs_rehash, new_opaque_token,
                               password_problems, verify_password)
from app.models import RefreshToken, Role, User, UserToken
from app.models.base import utcnow
from app.services import audit, email

_INVALID = ApiError(401, "invalid_credentials", "The e-mail address or password is incorrect.")
# Hash verified when the e-mail is unknown, so response time does not reveal which addresses have accounts.
_DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$hZa68ZEbKbGAElrMXbkzZA$xvPPhlyDsydBvllWtuvjQ1asuj/hmIKW1F+yQ+NZ5gY"


def _check_password(password: str) -> None:
    problems = password_problems(password)
    if problems:
        raise bad_request("The password needs " + ", ".join(problems) + ".", "weak_password", problems)


def find_user(db: Session, email_address: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email_address.strip().lower()))


def _issue_user_token(db: Session, user: User, purpose: str, lifetime: timedelta) -> str:
    for old in db.scalars(select(UserToken).where(UserToken.user_id == user.id, UserToken.purpose == purpose, UserToken.used_at.is_(None))):
        old.used_at = utcnow()                    # only the newest link works
    token, digest = new_opaque_token()
    db.add(UserToken(user_id=user.id, purpose=purpose, token_hash=digest, expires_at=utcnow() + lifetime))
    return token


def _consume_user_token(db: Session, token: str, purpose: str) -> User:
    row = db.scalar(select(UserToken).where(UserToken.token_hash == hash_token(token), UserToken.purpose == purpose))
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise bad_request("This link is invalid or has expired. Request a new one.", "token_invalid")
    row.used_at = utcnow()
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise bad_request("This link is invalid or has expired. Request a new one.", "token_invalid")
    return user


def register(db: Session, data: dict, ip: str | None) -> User:
    _check_password(data["password"])
    if find_user(db, data["email"]) is not None:
        raise ApiError(409, "email_taken", "An account with this e-mail address already exists.")
    role = db.scalar(select(Role).where(Role.name == "researcher"))
    if role is None:
        raise ApiError(500, "setup_incomplete", "The database has no roles. Run database/schema.sql first.")
    user = User(email=data["email"].strip().lower(), password_hash=hash_password(data["password"]), full_name=data["full_name"],
                institution=data.get("institution"), department=data.get("department"), academic_level=data.get("academic_level"))
    user.roles = [role]
    db.add(user)
    db.flush()
    token = _issue_user_token(db, user, "email_verify", timedelta(hours=get_settings().EMAIL_VERIFY_HOURS))
    audit.record(db, action="user.registered", user_id=user.id, entity_type="user", entity_id=user.id, ip=ip)
    db.commit()
    email.send_verification(user.email, token)
    return user


def _session_tokens(db: Session, user: User, user_agent: str | None, ip: str | None) -> dict:
    settings = get_settings()
    access, expires_in = create_access_token(user.id, user.role_names)
    refresh, digest = new_opaque_token()
    db.add(RefreshToken(user_id=user.id, token_hash=digest, user_agent=(user_agent or "")[:255] or None, ip_address=ip,
                        expires_at=utcnow() + timedelta(days=settings.REFRESH_TOKEN_DAYS)))
    return {"access_token": access, "token_type": "bearer", "expires_in": expires_in, "refresh_token": refresh, "user": user.to_dict()}


def login(db: Session, email_address: str, password: str, user_agent: str | None, ip: str | None) -> dict:
    settings = get_settings()
    user = find_user(db, email_address)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise _INVALID
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise ApiError(423, "account_locked", f"Too many failed attempts. Try again in about {minutes} minute(s).")
    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=settings.LOCKOUT_MINUTES)
            user.failed_login_count = 0
            audit.record(db, action="user.locked", user_id=user.id, entity_type="user", entity_id=user.id, ip=ip)
        db.commit()
        raise _INVALID
    if not user.is_active:
        raise ApiError(403, "account_disabled", "This account has been deactivated. Contact an administrator.")
    if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_email_verified:
        raise ApiError(403, "email_not_verified", "Verify your e-mail address before signing in. Check your inbox for the link.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
    tokens = _session_tokens(db, user, user_agent, ip)
    audit.record(db, action="user.login", user_id=user.id, entity_type="user", entity_id=user.id, ip=ip)
    db.commit()
    return tokens


def refresh(db: Session, refresh_token: str, user_agent: str | None, ip: str | None) -> dict:
    """Rotate the refresh token. Presenting a token that was already used is
    treated as theft: every session of that user is revoked."""
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token)))
    invalid = ApiError(401, "token_invalid", "Your session has expired. Please sign in again.")
    if row is None:
        raise invalid
    if row.revoked_at is not None:
        revoke_all_sessions(db, row.user_id)
        audit.record(db, action="user.refresh_token_reuse", user_id=row.user_id, entity_type="user", entity_id=row.user_id, ip=ip)
        db.commit()
        raise invalid
    if row.expires_at < utcnow():
        raise invalid
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise invalid
    row.revoked_at = utcnow()
    tokens = _session_tokens(db, user, user_agent, ip)
    db.commit()
    return tokens


def revoke_all_sessions(db: Session, user_id: int, except_id: int | None = None) -> int:
    count = 0
    for row in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))):
        if row.id != except_id:
            row.revoked_at = utcnow()
            count += 1
    return count


def logout(db: Session, user: User, refresh_token: str | None, everywhere: bool = False) -> None:
    if everywhere or not refresh_token:
        revoke_all_sessions(db, user.id)
    else:
        row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token), RefreshToken.user_id == user.id))
        if row is not None and row.revoked_at is None:
            row.revoked_at = utcnow()
    audit.record(db, action="user.logout", user_id=user.id, entity_type="user", entity_id=user.id)
    db.commit()


def active_sessions(db: Session, user_id: int) -> list[RefreshToken]:
    return list(db.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None),
                                                      RefreshToken.expires_at > utcnow()).order_by(RefreshToken.id.desc())))


def forgot_password(db: Session, email_address: str, ip: str | None) -> None:
    """Always succeeds from the caller's point of view, so the endpoint cannot
    be used to discover which e-mail addresses are registered."""
    user = find_user(db, email_address)
    if user is None or not user.is_active:
        return
    token = _issue_user_token(db, user, "password_reset", timedelta(minutes=get_settings().PASSWORD_RESET_MINUTES))
    audit.record(db, action="user.password_reset_requested", user_id=user.id, entity_type="user", entity_id=user.id, ip=ip)
    db.commit()
    email.send_password_reset(user.email, token)


def reset_password(db: Session, token: str, new_password: str, ip: str | None) -> None:
    _check_password(new_password)
    user = _consume_user_token(db, token, "password_reset")
    user.password_hash = hash_password(new_password)
    user.failed_login_count, user.locked_until = 0, None
    revoke_all_sessions(db, user.id)                 # sign out everywhere after a reset
    audit.record(db, action="user.password_reset", user_id=user.id, entity_type="user", entity_id=user.id, ip=ip)
    db.commit()


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise bad_request("The current password is incorrect.", "invalid_credentials")
    _check_password(new)
    user.password_hash = hash_password(new)
    revoke_all_sessions(db, user.id)
    audit.record(db, action="user.password_changed", user_id=user.id, entity_type="user", entity_id=user.id)
    db.commit()


def verify_email(db: Session, token: str) -> User:
    user = _consume_user_token(db, token, "email_verify")
    user.is_email_verified = True
    audit.record(db, action="user.email_verified", user_id=user.id, entity_type="user", entity_id=user.id)
    db.commit()
    return user


def resend_verification(db: Session, user: User) -> None:
    if user.is_email_verified:
        return
    token = _issue_user_token(db, user, "email_verify", timedelta(hours=get_settings().EMAIL_VERIFY_HOURS))
    db.commit()
    email.send_verification(user.email, token)
