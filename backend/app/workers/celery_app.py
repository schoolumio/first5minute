"""Celery application and beat schedule.

Start a worker:  celery -A app.workers.celery_app worker -l info -Q default,ingestion
Start beat:      celery -A app.workers.celery_app beat -l info
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging()
log = get_logger(__name__)

celery_app = Celery("projectfive", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={"app.workers.celery_app.sync_fixtures": {"queue": "ingestion"}},
    beat_schedule={
        "sync-fixtures": {"task": "app.workers.celery_app.sync_fixtures", "schedule": crontab(minute="*/30")},
        "scan": {"task": "app.workers.celery_app.scan", "schedule": crontab(minute="5,35")},
        "settle": {"task": "app.workers.celery_app.settle", "schedule": crontab(minute="*/15")},
        "expire-subscriptions": {"task": "app.workers.celery_app.expire_subscriptions", "schedule": crontab(minute=0)},
        "train-weekly": {"task": "app.workers.celery_app.train", "schedule": crontab(day_of_week="sun", hour=4, minute=23)},
        "backtest-nightly": {"task": "app.workers.celery_app.backtest", "schedule": crontab(hour=3, minute=17)},
    },
)


def _run(name: str) -> dict:
    from app.workers.jobs import run_named

    with SessionLocal() as db:
        try:
            return run_named(db, name)
        except Exception:
            db.rollback()
            log.exception("job_failed", job=name)
            raise


@celery_app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def sync_fixtures() -> dict:
    return _run("sync")


@celery_app.task
def scan() -> dict:
    return _run("scan")


@celery_app.task
def settle() -> dict:
    return _run("settle")


@celery_app.task
def expire_subscriptions() -> dict:
    return _run("expire")


@celery_app.task
def backtest() -> dict:
    return _run("backtest")


@celery_app.task
def train() -> dict:
    return _run("train")
