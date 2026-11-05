"""Booking Code Converter API.

Flow: POST /decode -> POST /{id}/match -> POST /{id}/generate. Requires a signed-in, verified user. Nothing here places a bet.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_verified
from app.booking_converter.errors import ConverterError, FeatureDisabled
from app.booking_converter.service import ConversionService
from app.core.config import get_settings
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.models import User

router = APIRouter(prefix="/booking-converter", tags=["booking-converter"])

_RECORDED_FAILURES = {"invalid_code", "code_not_found", "integration_unavailable", "upstream_error", "unsupported_bookmaker"}


class DecodeIn(BaseModel):
    code: str = Field(min_length=3, max_length=64)
    source: str = Field(min_length=2, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    destination: str = Field(min_length=2, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")


class GenerateIn(BaseModel):
    proceed_with_partial: bool = False


def _svc(request: Request, user: User, db: Session) -> ConversionService:
    if not get_settings().booking_converter_enabled:
        raise FeatureDisabled()
    return ConversionService(db, user, client_ip(request))


def _throttle(user: User) -> None:
    s = get_settings()
    if not s.rate_limit_enabled:
        return
    ok_min, retry = limiter.hit(f"bc:min:{user.id}", s.booking_converter_per_minute, 60)
    ok_hour, retry_h = limiter.hit(f"bc:hour:{user.id}", s.booking_converter_per_hour, 3600)
    if not (ok_min and ok_hour):
        raise HTTPException(429, {"message": "You're converting too quickly. Please wait a little and try again.", "code": "rate_limited"},
                            headers={"Retry-After": str(retry if not ok_min else retry_h)})


@router.get("/bookmakers")
def bookmakers(request: Request, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    return {"enabled": get_settings().booking_converter_enabled, "bookmakers": ConversionService(db, user).bookmakers()}


@router.post("/decode")
def decode(body: DecodeIn, request: Request, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    svc = _svc(request, user, db)
    _throttle(user)
    try:
        return svc.decode(body.code, body.source, body.destination)
    except ConverterError as exc:
        db.rollback()
        if exc.code in _RECORDED_FAILURES:
            svc.record_failure(body.source, body.destination, exc.code)
        raise


class TicketIn(BaseModel):
    destination: str = Field(min_length=2, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    prediction_ids: list[int] = Field(min_length=1, max_length=20)


class PreviewIn(BaseModel):
    prediction_ids: list[int] = Field(min_length=1, max_length=20)


@router.post("/ticket/preview")
def ticket_preview(body: PreviewIn, request: Request, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    """Fresh analysis and availability for the scanner picks on a ticket."""
    return {"items": _svc(request, user, db).ticket_preview(body.prediction_ids)}


@router.post("/ticket")
def ticket(body: TicketIn, request: Request, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    svc = _svc(request, user, db)
    _throttle(user)
    return svc.ticket(body.destination, body.prediction_ids)


@router.post("/{conversion_id}/match")
def match(conversion_id: str, request: Request, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    return _svc(request, user, db).match(conversion_id)


@router.post("/{conversion_id}/generate")
def generate(conversion_id: str, body: GenerateIn, request: Request, user: User = Depends(require_verified),
             db: Session = Depends(get_db)) -> dict:
    return _svc(request, user, db).generate(conversion_id, body.proceed_with_partial)


@router.get("/history")
def history(request: Request, user: User = Depends(require_verified), db: Session = Depends(get_db)) -> dict:
    return {"items": ConversionService(db, user).history()}
