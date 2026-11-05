"""Booking-converter history. Stores outcomes and counts only: never booking codes, selections or credentials."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class BookingConversion(TimestampMixin, Base):
    __tablename__ = "booking_conversions"
    __table_args__ = (Index("ix_booking_conversions_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source_bookmaker: Mapped[str] = mapped_column(String(48))
    destination_bookmaker: Mapped[str] = mapped_column(String(48))
    # started | matched | partial | unmatched | generated | manual | generation_failed | failed
    status: Mapped[str] = mapped_column(String(24), default="started")
    selections_total: Mapped[int] = mapped_column(Integer, default=0)
    selections_matched: Mapped[int] = mapped_column(Integer, default=0)
    code_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(48))
