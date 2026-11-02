"""Transactional email with pluggable backends.

* ``console`` (development): logs the message, including links, to stdout.
* ``memory`` (tests): appends to ``OUTBOX``.
* ``smtp`` (production): sends via the configured SMTP relay.
"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class SentEmail:
    to: str
    subject: str
    body: str


OUTBOX: list[SentEmail] = []


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.email_backend == "memory":
        OUTBOX.append(SentEmail(to, subject, body))
        return
    if settings.email_backend == "console":
        log.info("email_console_backend", to=to, subject=subject, body=body)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.email_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host or "localhost", settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(msg)


def send_verification_email(to: str, token: str) -> None:
    url = f"{get_settings().frontend_url}/verify-email?token={token}"
    send_email(
        to,
        "Verify your First5Minute account",
        f"Welcome to First5Minute.\n\nConfirm your email address:\n{url}\n\nThis link expires in 24 hours.",
    )


def send_password_reset_email(to: str, token: str) -> None:
    url = f"{get_settings().frontend_url}/reset-password?token={token}"
    send_email(
        to,
        "Reset your First5Minute password",
        f"A password reset was requested for your account.\n\nReset it here:\n{url}\n\n"
        "This link expires in 60 minutes. If you did not request it, ignore this email.",
    )
