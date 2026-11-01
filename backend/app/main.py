"""FastAPI application entrypoint."""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import csrf_protect, rate_limit
from app.api.v1 import account, admin, auth, fixtures, odds, predictions, scanner, subscriptions, system
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
log = get_logger("http")

app = FastAPI(
    title="Project Five API",
    version="0.1.0",
    description=(
        "Football intelligence for five-minute markets. Model outputs are statistical estimates, "
        "not guarantees. 18+ only."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    log.info("request", method=request.method, path=request.url.path, status=response.status_code,
             ms=round((time.perf_counter() - started) * 1000, 1))
    structlog.contextvars.clear_contextvars()
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errors})


common = [Depends(csrf_protect), Depends(rate_limit("api"))]
for r in (auth.router, account.router, fixtures.router, scanner.router, predictions.router, odds.router,
          subscriptions.router, admin.router, system.router):
    app.include_router(r, prefix=settings.api_prefix, dependencies=common)


@app.get("/healthz", tags=["system"])
def healthz() -> dict:
    return {"status": "ok"}
