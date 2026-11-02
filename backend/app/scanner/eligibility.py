"""Competition eligibility rules.

Not every league has equal data quality. For each competition we measure, over a
trailing window, the share of finished fixtures whose goal-event timeline
reconciles with the final score (the only fixtures usable for five-minute
features and settlement). That coverage decides:

* ``unassessed``  - too few finished fixtures to judge (no evidence against it;
  team-level sample rules still exclude individual matches).
* ``ineligible``  - coverage below ``min_coverage``: fixtures are shown as
  EXCLUDED with the reason instead of receiving a qualifying prediction.
* ``eligible``    - with a tier (high / medium / low) shown to users.

Admins can override per competition (``force_on`` / ``force_off``).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import Competition, Fixture
from app.services.settings import get_setting

BLOCK_PREFIX = "Competition not eligible: "


def classify(finished: int, complete: int, cfg: dict) -> tuple[str, str, float | None, str | None]:
    """Return (status, tier, coverage, reason) for a competition's counts."""
    cov = (complete / finished) if finished else None
    if finished < cfg["min_finished"]:
        return "unassessed", "unknown", cov, f"only {finished} finished fixtures so far (need {cfg['min_finished']} to assess)"
    assert cov is not None
    if cov < cfg["min_coverage"]:
        need = cfg["min_coverage"]
        return "ineligible", "low", cov, f"only {cov:.0%} of finished fixtures have a reconciled event timeline (need {need:.0%})"
    hi, med = cfg["high"], cfg["medium"]
    if finished >= hi["min_finished"] and cov >= hi["min_coverage"]:
        return "eligible", "high", cov, None
    if finished >= med["min_finished"] and cov >= med["min_coverage"]:
        return "eligible", "medium", cov, None
    return "eligible", "low", cov, f"timeline coverage {cov:.0%} is acceptable but below the medium-quality bar"


def assess_competitions(db: Session, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    cfg = get_setting(db, "scanner.eligibility")
    since = now - timedelta(days=int(cfg["lookback_days"]))
    counts = {
        cid: (int(n), int(ok))
        for cid, n, ok in db.execute(
            select(Fixture.competition_id, func.count(Fixture.id),
                   func.count(Fixture.id).filter(Fixture.timeline_status == "complete"))
            .where(Fixture.status == "finished", Fixture.kickoff_at >= since, Fixture.kickoff_at < now)
            .group_by(Fixture.competition_id)
        )
    }
    out = []
    for comp in db.scalars(select(Competition)):
        finished, complete = counts.get(comp.id, (0, 0))
        status, tier, cov, reason = classify(finished, complete, cfg)
        comp.eligibility_status, comp.data_quality_tier = status, tier
        comp.coverage_pct, comp.eligibility_reason, comp.finished_count, comp.assessed_at = cov, reason, finished, now
        out.append({"id": comp.id, "name": comp.name, "status": status, "tier": tier, "coverage": cov, "finished": finished})
    db.flush()
    return out


def eligibility_block(comp: Competition) -> str | None:
    """Reason string if fixtures of this competition must be EXCLUDED, else None."""
    if comp.eligibility_mode == "force_off":
        return BLOCK_PREFIX + "excluded by an administrator"
    if comp.eligibility_mode == "force_on":
        return None
    if comp.eligibility_status == "ineligible":
        return BLOCK_PREFIX + (comp.eligibility_reason or "insufficient data quality")
    return None
