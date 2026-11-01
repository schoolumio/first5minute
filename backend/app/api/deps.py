"""Shared FastAPI dependencies: DB session, auth, CSRF, rate limits, guards."""

from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.core.security import decode_access_token
from app.models import User
from app.services.entitlements import MIN_PLAN_FOR, entitlements

ACCESS_COOKIE = "pf_access"
REFRESH_COOKIE = "pf_refresh"
CSRF_COOKIE = "pf_csrf"
CSRF_HEADER = "x-csrf-token"


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, per_minute: int | None = None) -> Callable:
    def dep(request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        limit = per_minute or settings.rate_limit_default_per_minute
        allowed, retry = limiter.hit(f"{scope}:{client_ip(request)}", limit)
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, slow down.", headers={"Retry-After": str(retry)}
            )

    return dep


def auth_rate_limit(request: Request) -> None:
    rate_limit("auth", get_settings().rate_limit_auth_per_minute)(request)


def _token_from_request(request: Request) -> tuple[str | None, bool]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip(), False
    return request.cookies.get(ACCESS_COOKIE), True


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token, _ = _token_from_request(request)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        return None
    request.state.user_id = user.id
    return user


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return user


def require_verified(user: User = Depends(get_current_user)) -> User:
    if not user.is_verified and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Please verify your email address to continue.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


def require_feature(feature: str) -> Callable:
    def dep(user: User = Depends(require_verified), db: Session = Depends(get_db)) -> User:
        if not entitlements(db, user)["features"].get(feature):
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                {
                    "message": "Your plan does not include this feature.",
                    "feature": feature,
                    "required_plan": MIN_PLAN_FOR.get(feature),
                },
            )
        return user

    return dep


async def csrf_protect(request: Request) -> None:
    """Double-submit CSRF check for cookie-authenticated unsafe requests."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        return
    if not (request.cookies.get(ACCESS_COOKIE) or request.cookies.get(REFRESH_COOKIE)):
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or cookie != header:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")


class Pagination:
    def __init__(self, page: int = 1, page_size: int = 25):
        if page < 1:
            raise HTTPException(422, "page must be >= 1")
        if not 1 <= page_size <= 100:
            raise HTTPException(422, "page_size must be between 1 and 100")
        self.page, self.page_size = page, page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_response(items: list, total: int, p: Pagination) -> dict:
    return {
        "items": items,
        "total": total,
        "page": p.page,
        "page_size": p.page_size,
        "pages": (total + p.page_size - 1) // p.page_size,
    }
