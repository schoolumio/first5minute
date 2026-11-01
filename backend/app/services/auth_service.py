"""Registration, login, token rotation, email verification and password reset."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models import AuthToken, Role, User
from app.services.audit import audit
from app.services.email import send_password_reset_email, send_verification_email

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    user: User


def _issue_token(db: Session, user: User, purpose: str, ttl: timedelta, ua: str | None = None, ip: str | None = None) -> str:
    raw = generate_opaque_token()
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=utcnow() + ttl,
            user_agent=(ua or "")[:255] or None,
            ip_address=ip,
        )
    )
    db.flush()
    return raw


def _consume_token(db: Session, raw: str, purpose: str) -> AuthToken:
    tok = db.scalar(
        select(AuthToken).where(AuthToken.token_hash == hash_token(raw), AuthToken.purpose == purpose).with_for_update()
    )
    if tok is None or tok.used_at is not None or tok.expires_at <= utcnow():
        raise AuthError("Invalid or expired token", 400 if purpose != "refresh" else 401)
    tok.used_at = utcnow()
    return tok


def register(db: Session, email: str, password: str, full_name: str | None, country: str | None, ip: str | None) -> User:
    email = email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        # Do not reveal whether the email exists beyond what's needed for UX:
        # we raise a generic conflict.
        raise AuthError("An account with this email already exists", 409)
    role = db.scalar(select(Role).where(Role.name == "user"))
    assert role is not None
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        country=country,
        role_id=role.id,
        notification_prefs={"scanner_qualified": True, "prediction_settled": False, "email": False},
    )
    db.add(user)
    db.flush()
    token = _issue_token(db, user, "verify_email", timedelta(hours=get_settings().email_token_ttl_hours))
    audit(db, "auth.register", user.id, "user", user.id, ip=ip)
    send_verification_email(user.email, token)
    return user


def login(db: Session, email: str, password: str, ua: str | None, ip: str | None) -> TokenPair:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    now = utcnow()
    if user is not None and user.locked_until and user.locked_until > now:
        raise AuthError("Account temporarily locked after repeated failed logins. Try again later.", 429)
    if user is None or not verify_password(password, user.password_hash):
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_login_attempts = 0
            audit(db, "auth.login_failed", user.id, "user", user.id, ip=ip)
        raise AuthError("Invalid email or password", 401)
    if not user.is_active:
        raise AuthError("Account is disabled", 403)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    audit(db, "auth.login", user.id, "user", user.id, ip=ip)
    return issue_session(db, user, ua, ip)


def issue_session(db: Session, user: User, ua: str | None, ip: str | None) -> TokenPair:
    settings = get_settings()
    refresh = _issue_token(db, user, "refresh", timedelta(days=settings.refresh_token_ttl_days), ua, ip)
    access = create_access_token(user.id, user.role.name)
    return TokenPair(access, refresh, user)


def refresh_session(db: Session, raw_refresh: str, ua: str | None, ip: str | None) -> TokenPair:
    """Rotate refresh tokens; reuse of a consumed token revokes all sessions."""
    tok = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(raw_refresh), AuthToken.purpose == "refresh"))
    if tok is not None and tok.used_at is not None:
        revoke_all_sessions(db, tok.user_id)
        audit(db, "auth.refresh_reuse_detected", tok.user_id, "user", tok.user_id, ip=ip)
        db.commit()
        raise AuthError("Session expired", 401)
    tok = _consume_token(db, raw_refresh, "refresh")
    user = db.get(User, tok.user_id)
    if user is None or not user.is_active:
        raise AuthError("Session expired", 401)
    return issue_session(db, user, ua, ip)


def revoke_refresh(db: Session, raw_refresh: str) -> None:
    db.execute(
        update(AuthToken)
        .where(AuthToken.token_hash == hash_token(raw_refresh), AuthToken.used_at.is_(None))
        .values(used_at=utcnow())
    )


def revoke_all_sessions(db: Session, user_id: int) -> None:
    db.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user_id, AuthToken.purpose == "refresh", AuthToken.used_at.is_(None))
        .values(used_at=utcnow())
    )


def verify_email(db: Session, raw: str) -> User:
    tok = _consume_token(db, raw, "verify_email")
    user = db.get(User, tok.user_id)
    assert user is not None
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    audit(db, "auth.email_verified", user.id, "user", user.id)
    return user


def resend_verification(db: Session, user: User) -> None:
    if user.is_verified:
        return
    token = _issue_token(db, user, "verify_email", timedelta(hours=get_settings().email_token_ttl_hours))
    send_verification_email(user.email, token)


def forgot_password(db: Session, email: str, ip: str | None) -> None:
    """Always succeeds from the caller's perspective (no account enumeration)."""
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        return
    token = _issue_token(db, user, "reset_password", timedelta(minutes=get_settings().password_reset_ttl_minutes))
    audit(db, "auth.password_reset_requested", user.id, "user", user.id, ip=ip)
    send_password_reset_email(user.email, token)


def reset_password(db: Session, raw: str, new_password: str, ip: str | None) -> None:
    tok = _consume_token(db, raw, "reset_password")
    user = db.get(User, tok.user_id)
    assert user is not None
    user.password_hash = hash_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    revoke_all_sessions(db, user.id)
    audit(db, "auth.password_reset", user.id, "user", user.id, ip=ip)


def change_password(db: Session, user: User, current: str, new: str, ip: str | None) -> None:
    if not verify_password(current, user.password_hash):
        raise AuthError("Current password is incorrect", 400)
    user.password_hash = hash_password(new)
    revoke_all_sessions(db, user.id)
    audit(db, "auth.password_changed", user.id, "user", user.id, ip=ip)
