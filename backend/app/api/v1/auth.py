"""Authentication endpoints. Sessions use httpOnly cookies (browser) or bearer tokens (API)."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    auth_rate_limit,
    client_ip,
    get_current_user,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import password_policy_errors
from app.models import User
from app.schemas.common import user_out
from app.services import auth_service as svc
from app.services.entitlements import entitlements
from app.services.settings import get_setting

router = APIRouter(prefix="/auth", tags=["auth"])


class PasswordModel(BaseModel):
    @staticmethod
    def check(v: str) -> str:
        errs = password_policy_errors(v)
        if errs:
            raise ValueError("Password " + ", ".join(errs))
        return v


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    accept_terms: bool
    confirm_age: bool

    _pw = field_validator("password")(PasswordModel.check)


class LoginIn(BaseModel):
    # Plain string: login only looks up an existing account, so syntax rules that
    # may change over time (e.g. reserved TLDs) must not lock users out.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(max_length=128)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class EmailIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(max_length=128)
    _pw = field_validator("password")(PasswordModel.check)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)
    _pw = field_validator("new_password")(PasswordModel.check)


def _set_session_cookies(response: Response, pair: svc.TokenPair, request: Request | None = None) -> None:
    s = get_settings()
    common = {"secure": s.cookie_secure, "samesite": "lax", "domain": s.cookie_domain}
    response.set_cookie(ACCESS_COOKIE, pair.access_token, max_age=s.access_token_ttl_minutes * 60, httponly=True,
                        path="/", **common)
    response.set_cookie(REFRESH_COOKIE, pair.refresh_token, max_age=s.refresh_token_ttl_days * 86400, httponly=True,
                        path=f"{s.api_prefix}/auth", **common)
    # Keep an existing CSRF token stable for the session (avoids races between tabs).
    csrf_value = (request.cookies.get(CSRF_COOKIE) if request is not None else None) or secrets.token_urlsafe(24)
    response.set_cookie(CSRF_COOKIE, csrf_value, max_age=s.refresh_token_ttl_days * 86400,
                        httponly=False, path="/", **common)


def _clear_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(ACCESS_COOKIE, path="/", domain=s.cookie_domain)
    response.delete_cookie(REFRESH_COOKIE, path=f"{s.api_prefix}/auth", domain=s.cookie_domain)
    response.delete_cookie(CSRF_COOKIE, path="/", domain=s.cookie_domain)


def _session_body(db: Session, pair: svc.TokenPair) -> dict:
    return {
        "user": user_out(pair.user, entitlements(db, pair.user)),
        "access_token": pair.access_token,
        "token_type": "bearer",
        "expires_in": get_settings().access_token_ttl_minutes * 60,
    }


def _handle(exc: svc.AuthError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


@router.post("/register", status_code=201, dependencies=[Depends(auth_rate_limit)])
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> dict:
    if not get_setting(db, "platform.flags").get("registrations_open", True):
        raise HTTPException(503, "Registrations are temporarily closed")
    if not body.accept_terms or not body.confirm_age:
        raise HTTPException(422, "You must accept the terms and confirm you are of legal betting age (18+)")
    try:
        user = svc.register(db, body.email, body.password, body.full_name, body.country.upper() if body.country else None,
                            client_ip(request))
    except svc.AuthError as exc:
        raise _handle(exc) from exc
    db.commit()
    return {"message": "Account created. Check your email to verify your address.", "user_id": user.id}


@router.post("/login", dependencies=[Depends(auth_rate_limit)])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    try:
        pair = svc.login(db, body.email, body.password, request.headers.get("user-agent"), client_ip(request))
    except svc.AuthError as exc:
        db.commit()  # persist failed-attempt counters / audit
        raise _handle(exc) from exc
    db.commit()
    _set_session_cookies(response, pair)
    return _session_body(db, pair)


@router.post("/refresh", dependencies=[Depends(auth_rate_limit)])
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(401, "No session")
    try:
        pair = svc.refresh_session(db, raw, request.headers.get("user-agent"), client_ip(request))
    except svc.AuthError as exc:
        _clear_cookies(response)
        raise _handle(exc) from exc
    db.commit()
    _set_session_cookies(response, pair, request)
    return _session_body(db, pair)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        svc.revoke_refresh(db, raw)
        db.commit()
    _clear_cookies(response)
    return {"message": "Signed out"}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return user_out(user, entitlements(db, user))


@router.post("/verify-email", dependencies=[Depends(auth_rate_limit)])
def verify_email(body: TokenIn, db: Session = Depends(get_db)) -> dict:
    try:
        svc.verify_email(db, body.token)
    except svc.AuthError as exc:
        raise _handle(exc) from exc
    db.commit()
    return {"message": "Email verified"}


@router.post("/resend-verification", dependencies=[Depends(auth_rate_limit)])
def resend_verification(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    svc.resend_verification(db, user)
    db.commit()
    return {"message": "If your email is unverified, a new link has been sent."}


@router.post("/forgot-password", dependencies=[Depends(auth_rate_limit)])
def forgot_password(body: EmailIn, request: Request, db: Session = Depends(get_db)) -> dict:
    svc.forgot_password(db, body.email, client_ip(request))
    db.commit()
    return {"message": "If an account exists for that email, a reset link has been sent."}


@router.post("/reset-password", dependencies=[Depends(auth_rate_limit)])
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        svc.reset_password(db, body.token, body.password, client_ip(request))
    except svc.AuthError as exc:
        raise _handle(exc) from exc
    db.commit()
    return {"message": "Password updated. Please sign in."}


@router.post("/change-password", dependencies=[Depends(auth_rate_limit)])
def change_password(body: ChangePasswordIn, request: Request, response: Response, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> dict:
    try:
        svc.change_password(db, user, body.current_password, body.new_password, client_ip(request))
    except svc.AuthError as exc:
        raise _handle(exc) from exc
    pair = svc.issue_session(db, user, request.headers.get("user-agent"), client_ip(request))
    db.commit()
    _set_session_cookies(response, pair, request)
    return {"message": "Password changed. Other sessions were signed out."}


@router.get("/csrf", status_code=status.HTTP_204_NO_CONTENT)
def csrf(response: Response) -> Response:
    """Ensures a CSRF cookie exists (used by the frontend on first load)."""
    s = get_settings()
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(24), httponly=False, samesite="lax", secure=s.cookie_secure,
                        path="/", domain=s.cookie_domain)
    response.status_code = 204
    return response
