"""Conversion workflow: decode -> match -> generate.

Each step is a separate call so the UI can show real progress and let the user decide about unmatched selections. Between
steps the state lives in a short-lived server-side session (owner-bound), never in the browser. History rows store counts and
outcomes only (no booking codes, no selections).
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.booking_converter.adapters.base import BookmakerAdapter
from app.booking_converter.adapters.registry import all_adapters, get_adapter
from app.booking_converter.domain import Pick, Selection
from app.booking_converter.errors import (
    ConversionBusy,
    ConversionNotFound,
    ConverterError,
    FeatureDisabled,
    GenerationFailed,
    IntegrationUnavailable,
    InvalidBookingCode,
    NeedsDecision,
    NothingToConvert,
    SameBookmaker,
    SelfExcluded,
    UpstreamError,
    WrongState,
)
from app.booking_converter.matcher import MATCHED, ODDS_CHANGED, UNAVAILABLE, UNMATCHED, SelectionResult, match_betslip
from app.booking_converter.store import ConversionStore
from app.booking_converter.store import store as default_store
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.logging import get_logger
from app.models import BookingConversion, User
from app.services.responsible import limit_status

log = get_logger(__name__)

NOTICE = ("18+. First5Minute only converts betslips. It never places bets or holds money. Odds change quickly: check every "
          "selection and price on the bookmaker before you bet, and only stake what you can afford to lose.")
MAX_GENERATION_ATTEMPTS = 3


def _money(d: Decimal | None) -> str | None:
    return str(d.quantize(Decimal("0.01"))) if d is not None else None


def _result_dict(r: SelectionResult) -> dict:
    dest = None
    if r.dest_event is not None:
        dest = {"event_id": r.dest_event.id, "home_team": r.dest_event.home_team, "away_team": r.dest_event.away_team,
                "start_time": r.dest_event.start_time.isoformat() if r.dest_event.start_time else None,
                "competition": r.dest_event.competition,
                "market_id": r.dest_market.id if r.dest_market else None,
                "market_name": r.dest_market.name if r.dest_market else None,
                "outcome_id": r.dest_outcome.id if r.dest_outcome else None,
                "outcome": r.dest_outcome.name if r.dest_outcome else None,
                "odds": _money(r.dest_outcome.odds) if r.dest_outcome else None}
    return {
        "index": r.index, "source": r.source.to_dict(), "status": r.status, "reason_code": r.reason_code, "reason": r.reason,
        "confidence": r.confidence, "interpreted_as": r.canon.describe() if r.canon else None, "destination": dest,
        "odds": {"original": _money(r.source.odds), "destination": _money(r.dest_outcome.odds) if r.matched and r.dest_outcome else None,
                 "change": r.odds_change},
    }


def _pick_dict(p: Pick) -> dict:
    return {"event_id": p.event_id, "market_id": p.market_id, "outcome_id": p.outcome_id, "specifier": p.specifier,
            "expected_odds": str(p.expected_odds) if p.expected_odds is not None else None}


def _pick_from(d: dict) -> Pick:
    return Pick(event_id=d["event_id"], market_id=d["market_id"], outcome_id=d["outcome_id"], specifier=d.get("specifier"),
                expected_odds=Decimal(d["expected_odds"]) if d.get("expected_odds") else None)


def _info(a: BookmakerAdapter) -> dict:
    return {"code": a.code, "name": a.name, "is_demo": a.is_demo, "website": a.website,
            "can_decode": a.capabilities.can_decode and a.available(),
            "can_be_destination": a.capabilities.can_find_events and a.available(),
            "can_generate": a.capabilities.can_generate and a.available(), "available": a.available(),
            "message": a.user_message()}


class ConversionService:
    def __init__(self, db: Session, user: User, ip: str | None = None, session_store: ConversionStore | None = None):
        self.db, self.user, self.ip = db, user, ip
        self.store = session_store or default_store
        self.settings = get_settings()

    # ---- helpers ---------------------------------------------------------------------------------------
    def _guard(self) -> None:
        if not self.settings.booking_converter_enabled:
            raise FeatureDisabled()
        if limit_status(self.db, self.user)["self_excluded"]:
            raise SelfExcluded()

    def _key(self, sid: str) -> str:
        return f"session:{sid}"

    def _load(self, sid: str) -> dict:
        rec = self.store.get_json(self._key(sid))
        if rec is None or rec.get("owner") != self.user.id:
            raise ConversionNotFound()
        return rec

    def _save(self, rec: dict) -> None:
        self.store.put(self._key(rec["id"]), rec, self.settings.booking_converter_session_ttl_seconds)

    def _history(self, rec: dict) -> BookingConversion | None:
        return self.db.get(BookingConversion, rec["history_id"]) if rec.get("history_id") else None

    # ---- public views ----------------------------------------------------------------------------------
    def bookmakers(self) -> list[dict]:
        rows = []
        for a in all_adapters().values():
            info = _info(a)
            if self.user.is_admin and not a.available():
                info["setup"] = a.setup_note
            rows.append(info)
        rows.sort(key=lambda r: (r["is_demo"], not r["available"], r["name"].lower()))
        return rows

    def view(self, rec: dict, deduplicated: bool = False) -> dict:
        src, dst = get_adapter(rec["source"]), get_adapter(rec["destination"])
        results = rec.get("results")
        sels = [Selection.from_dict(s) for s in rec["selections"]]
        if results is None:
            items = [{"index": i, "source": s.to_dict(), "status": "pending", "reason_code": None, "reason": None, "confidence": None,
                      "interpreted_as": None, "destination": None,
                      "odds": {"original": _money(s.odds), "destination": None, "change": None}} for i, s in enumerate(sels)]
        else:
            items = results
        matched = [i for i in items if i["status"] in (MATCHED, ODDS_CHANGED)]
        counts = {"original": len(items), "matched": len(matched) if results is not None else 0,
                  "unmatched": sum(i["status"] == UNMATCHED for i in items),
                  "unavailable": sum(i["status"] == UNAVAILABLE for i in items),
                  "odds_changed": sum(i["status"] == ODDS_CHANGED for i in items)}
        original_total = None
        if sels and all(s.odds is not None for s in sels):
            original_total = Decimal(1)
            for s in sels:
                original_total *= s.odds
        dest_total = None
        if matched:
            dest_total = Decimal(1)
            for i in matched:
                dest_total *= Decimal(i["destination"]["odds"])
        needs_decision = results is not None and 0 < counts["matched"] < counts["original"] and rec["state"] == "matched"
        return {
            "id": rec["id"], "state": rec["state"], "deduplicated": deduplicated, "is_demo": rec["is_demo"],
            "source": {"code": src.code, "name": src.name, "is_demo": src.is_demo},
            "destination": {"code": dst.code, "name": dst.name, "is_demo": dst.is_demo, "website": dst.website,
                            "can_generate": dst.capabilities.can_generate and dst.available()},
            "counts": counts, "selections": items,
            "totals": {"original_odds": _money(original_total), "destination_odds": _money(dest_total),
                       "destination_covers_all": bool(matched) and counts["matched"] == counts["original"]},
            "booking": rec.get("booking"), "needs_decision": needs_decision, "betslip_text": self._slip_text(rec, dst) if matched else None,
            "notice": NOTICE,
        }

    @staticmethod
    def _slip_text(rec: dict, dst: BookmakerAdapter) -> str | None:
        items = [i for i in (rec.get("results") or []) if i["status"] in (MATCHED, ODDS_CHANGED)]
        if not items:
            return None
        lines = [f"{dst.name} betslip ({len(items)} selection{'s' if len(items) != 1 else ''})"]
        for n, i in enumerate(items, 1):
            d = i["destination"]
            lines.append(f"{n}. {d['home_team']} vs {d['away_team']} - {d['market_name']}"
                         + (f" ({d['outcome']})" if d.get("outcome") else "") + f" @ {d['odds']}")
        return "\n".join(lines)

    # ---- step 1: decode --------------------------------------------------------------------------------
    def decode(self, code: str, source: str, destination: str) -> dict:
        t0 = time.monotonic()
        self._guard()
        src, dst = get_adapter(source), get_adapter(destination)
        if src.code == dst.code:
            raise SameBookmaker()
        if not (src.capabilities.can_decode and src.available()):
            raise IntegrationUnavailable(f"{src.name} booking codes can't be read yet because no official integration is connected.")
        if not (dst.capabilities.can_find_events and dst.available()):
            raise IntegrationUnavailable(f"{dst.name} can't be used as a destination yet because no official integration is connected.")
        norm = src.normalize_code(code)
        h = hashlib.sha256(f"{self.user.id}|{src.code}|{dst.code}|{norm}".encode()).hexdigest()[:32]
        recent = self.store.get(f"dd:{h}")
        if recent:
            try:
                return self.view(self._load(recent), deduplicated=True)
            except ConversionNotFound:
                pass
        if not self.store.claim(f"lock:{h}", 30):
            raise ConversionBusy()
        try:
            try:
                decoded = src.decode(norm)
            except ConverterError:
                raise
            except Exception as exc:  # noqa: BLE001 - adapter bug or network failure must not leak details
                log.error("booking_decode_failed", bookmaker=src.code, error=type(exc).__name__)
                raise UpstreamError() from exc
            if not decoded.selections:
                raise InvalidBookingCode("That booking code has no selections.")
            if len(decoded.selections) > self.settings.booking_converter_max_selections:
                raise InvalidBookingCode("That booking code has too many selections (the limit is "
                                         f"{self.settings.booking_converter_max_selections}).")
            row = BookingConversion(user_id=self.user.id, source_bookmaker=src.code, destination_bookmaker=dst.code, status="started",
                                    selections_total=len(decoded.selections), is_demo=decoded.is_demo or dst.is_demo)
            self.db.add(row)
            self.db.flush()
            rec = {"id": hashlib.sha256(f"{h}{time.time_ns()}".encode()).hexdigest()[:24], "owner": self.user.id, "source": src.code,
                   "destination": dst.code, "state": "decoded", "selections": [s.to_dict() for s in decoded.selections],
                   "results": None, "picks": {}, "booking": None, "is_demo": decoded.is_demo or dst.is_demo or src.is_demo,
                   "history_id": row.id, "gen_attempts": 0, "created_at": utcnow().isoformat()}
            self._save(rec)
            self.store.put(f"dd:{h}", rec["id"], 120)
            self.db.commit()
            log.info("booking_conversion_decoded", source=src.code, destination=dst.code, selections=len(decoded.selections),
                     ms=round((time.monotonic() - t0) * 1000))
            return self.view(rec)
        finally:
            self.store.release(f"lock:{h}")

    # ---- step 2: match ---------------------------------------------------------------------------------
    def match(self, conversion_id: str) -> dict:
        t0 = time.monotonic()
        self._guard()
        rec = self._load(conversion_id)
        if rec["state"] != "decoded":
            return self.view(rec)                     # already matched: idempotent
        if not self.store.claim(f"lock:match:{rec['id']}", 60):
            raise ConversionBusy()
        try:
            dst = get_adapter(rec["destination"])
            sels = [Selection.from_dict(s) for s in rec["selections"]]

            def lookup(q):
                try:
                    return dst.find_events(q)
                except ConverterError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.error("booking_lookup_failed", bookmaker=dst.code, error=type(exc).__name__)
                    raise UpstreamError() from exc

            results = match_betslip(sels, lookup, self.settings.booking_converter_match_deadline_seconds, datetime.now(UTC))
            rec["results"] = [_result_dict(r) for r in results]
            rec["picks"] = {str(r.index): _pick_dict(r.pick) for r in results if r.pick is not None and r.matched}
            rec["state"] = "matched"
            n_ok = sum(r.matched for r in results)
            row = self._history(rec)
            if row is not None:
                row.selections_matched = n_ok
                row.status = "matched" if n_ok == len(results) else ("partial" if n_ok else "unmatched")
            self._save(rec)
            self.db.commit()
            log.info("booking_conversion_matched", source=rec["source"], destination=rec["destination"], selections=len(results),
                     matched=n_ok, ms=round((time.monotonic() - t0) * 1000))
            return self.view(rec)
        finally:
            self.store.release(f"lock:match:{rec['id']}")

    # ---- step 3: generate ------------------------------------------------------------------------------
    def generate(self, conversion_id: str, proceed_with_partial: bool = False) -> dict:
        t0 = time.monotonic()
        self._guard()
        rec = self._load(conversion_id)
        if rec["state"] in ("generated", "manual"):
            return self.view(rec)                     # idempotent: a code is never generated twice
        if rec["state"] != "matched":
            raise WrongState()
        items = rec["results"] or []
        n_ok = sum(i["status"] in (MATCHED, ODDS_CHANGED) for i in items)
        if n_ok == 0:
            raise NothingToConvert()
        if n_ok < len(items) and not proceed_with_partial:
            raise NeedsDecision()
        dst = get_adapter(rec["destination"])
        row = self._history(rec)
        if not (dst.capabilities.can_generate and dst.available()):
            rec["booking"] = {"status": "manual", "code": None, "share_url": None, "is_demo": dst.is_demo,
                              "message": f"{dst.name} doesn't offer automatic booking codes through First5Minute. Your slip is recreated "
                                         "below: copy it and add the selections on the bookmaker yourself."}
            rec["state"] = "manual"
            if row is not None:
                row.status = "manual"
            self._save(rec)
            self.db.commit()
            return self.view(rec)
        if rec.get("gen_attempts", 0) >= MAX_GENERATION_ATTEMPTS:
            raise GenerationFailed("Too many attempts. Start a new conversion.")
        if not self.store.claim(f"lock:gen:{rec['id']}", 60):
            raise ConversionBusy()
        try:
            rec["gen_attempts"] = rec.get("gen_attempts", 0) + 1
            picks = [_pick_from(rec["picks"][str(i["index"])]) for i in items if i["status"] in (MATCHED, ODDS_CHANGED)]
            booking: dict
            try:
                created = dst.create_booking(picks)
                if not dst.valid_generated_code(created.code):
                    raise GenerationFailed("The bookmaker returned something that isn't a valid booking code.")
                booking = {"status": "generated", "code": created.code, "share_url": created.share_url,
                           "is_demo": bool(created.is_demo or dst.is_demo), "message": None}
                rec["state"] = "generated"
            except ConverterError as exc:
                booking = {"status": "failed", "code": None, "share_url": None, "is_demo": dst.is_demo, "message": exc.message}
            except Exception as exc:  # noqa: BLE001
                log.error("booking_generate_failed", bookmaker=dst.code, error=type(exc).__name__)
                booking = {"status": "failed", "code": None, "share_url": None, "is_demo": dst.is_demo,
                           "message": GenerationFailed.default_message}
            rec["booking"] = booking
            if row is not None:
                row.code_generated = booking["status"] == "generated"
                row.status = "generated" if booking["status"] == "generated" else "generation_failed"
                row.error_code = None if booking["status"] == "generated" else "generation_failed"
            self._save(rec)
            self.db.commit()
            log.info("booking_conversion_generated", destination=dst.code, status=booking["status"], selections=len(picks),
                     ms=round((time.monotonic() - t0) * 1000))
            return self.view(rec)
        finally:
            self.store.release(f"lock:gen:{rec['id']}")

    # ---- history ---------------------------------------------------------------------------------------
    def history(self, limit: int = 20) -> list[dict]:
        rows = self.db.scalars(select(BookingConversion).where(BookingConversion.user_id == self.user.id)
                               .order_by(BookingConversion.id.desc()).limit(limit)).all()
        names = {a.code: a.name for a in all_adapters().values()}
        return [{"id": r.id, "source": names.get(r.source_bookmaker, r.source_bookmaker),
                 "destination": names.get(r.destination_bookmaker, r.destination_bookmaker), "status": r.status,
                 "selections": r.selections_total, "matched": r.selections_matched, "code_generated": r.code_generated,
                 "is_demo": r.is_demo, "created_at": r.created_at.isoformat()} for r in rows]

    def record_failure(self, source: str, destination: str, error_code: str) -> None:
        """Count a failed start (no code or selections are stored)."""
        self.db.add(BookingConversion(user_id=self.user.id, source_bookmaker=source[:48], destination_bookmaker=destination[:48],
                                      status="failed", error_code=error_code[:48]))
        self.db.commit()

