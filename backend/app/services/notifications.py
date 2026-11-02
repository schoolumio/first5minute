"""Delivery of queued notification emails (the outbox pattern).

Business code records a ``Notification`` with ``email_requested=True`` inside its own transaction; this job emails it after
the commit, so a rolled-back change never sends a message and a mail outage never blocks billing or scanning.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.logging import get_logger
from app.models import Notification, User
from app.services.email import send_email

log = get_logger(__name__)
MAX_AGE = timedelta(days=3)  # stale queued mail is dropped, not sent days late


def deliver_notification_emails(db: Session, now: datetime | None = None, limit: int = 200) -> dict:
    now = now or utcnow()
    rows = db.scalars(
        select(Notification).where(Notification.email_requested.is_(True), Notification.emailed_at.is_(None))
        .order_by(Notification.id).limit(limit)
    ).all()
    stats = {"sent": 0, "failed": 0, "dropped": 0}
    base = get_settings().frontend_url
    for n in rows:
        user = db.get(User, n.user_id)
        if user is None or not user.is_active or now - n.created_at > MAX_AGE:
            n.emailed_at = now  # nothing to send (or too stale): close it so the outbox does not grow
            stats["dropped"] += 1
            continue
        link = f"\n\nOpen: {base}{n.link}" if n.link else ""
        try:
            send_email(user.email, f"First5Minute: {n.title}", f"{n.body}{link}\n\n-- First5Minute (statistics, not guarantees; 18+)")
        except Exception as exc:  # noqa: BLE001 - leave queued and retry on the next run
            log.warning("notification_email_failed", notification_id=n.id, error=str(exc))
            stats["failed"] += 1
            continue
        n.emailed_at = now
        stats["sent"] += 1
    db.flush()
    return stats
