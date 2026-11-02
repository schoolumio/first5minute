"""Shared response serialisers (plain dicts keep the API explicit and fast)."""

from __future__ import annotations

from app.models import Competition, Fixture, Prediction, Team, User


def team_out(t: Team) -> dict:
    return {"id": t.id, "name": t.name, "short_name": t.short_name, "country": t.country, "logo_url": t.logo_url,
            "is_demo": t.is_demo}


def competition_out(c: Competition) -> dict:
    return {"id": c.id, "name": c.name, "country": c.country, "type": c.type, "gender": c.gender,
            "logo_url": c.logo_url, "is_enabled": c.is_enabled, "data_quality_tier": c.data_quality_tier,
            "eligibility_status": c.eligibility_status, "eligibility_mode": c.eligibility_mode,
            "eligibility_reason": c.eligibility_reason, "coverage_pct": c.coverage_pct,
            "is_demo": c.is_demo}


def fixture_out(f: Fixture) -> dict:
    return {
        "id": f.id,
        "provider": f.provider,
        "competition": competition_out(f.competition),
        "home_team": team_out(f.home_team),
        "away_team": team_out(f.away_team),
        "kickoff_at": f.kickoff_at.isoformat(),
        "status": f.status,
        "round": f.round,
        "venue": f.venue,
        "score": {"home": f.home_score_ft, "away": f.away_score_ft, "home_ht": f.home_score_ht, "away_ht": f.away_score_ht},
        "timeline_status": f.timeline_status,
        "timeline_precision": f.timeline_precision,
        "data_version": f.data_version,
        "is_demo": f.is_demo,
    }


def prediction_out(p: Prediction, include_fixture: bool = True) -> dict:
    out = {
        "id": p.id,
        "fixture_id": p.fixture_id,
        "market": p.market_code,
        "probability": round(p.probability, 5),
        "confidence": p.confidence,
        "data_quality": p.data_quality,
        "category": p.category,
        "category_reasons": p.category_reasons,
        "sample_home": p.sample_home,
        "sample_away": p.sample_away,
        "lambda_home": p.lambda_home,
        "lambda_away": p.lambda_away,
        "components": p.components,
        "predicted_at": p.predicted_at.isoformat(),
        "kickoff_at": p.kickoff_at.isoformat(),
        "input_data_version": p.input_data_version,
        "is_current": p.is_current,
        "model": {
            "id": p.model_version.id,
            "name": p.model_version.name,
            "version": p.model_version.version,
            "algorithm": p.model_version.algorithm,
            "calibration_status": p.model_version.calibration_status,
        },
        "outcome": (
            {
                "result": p.outcome.result,
                "home_score_at_cutoff": p.outcome.home_score_at_cutoff,
                "away_score_at_cutoff": p.outcome.away_score_at_cutoff,
                "settled_at": p.outcome.settled_at.isoformat(),
                "revision": p.outcome.revision,
                "notes": p.outcome.notes,
            }
            if p.outcome
            else None
        ),
        "is_demo": p.is_demo,
    }
    if include_fixture:
        out["fixture"] = fixture_out(p.fixture)
    return out


def user_out(u: User, ent: dict | None = None) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "country": u.country,
        "timezone": u.timezone,
        "role": u.role.name,
        "email_verified": u.is_verified,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "notification_prefs": u.notification_prefs or {},
        "responsible_gambling": {
            "daily_stake_limit": float(u.rg_daily_stake_limit) if u.rg_daily_stake_limit is not None else None,
            "monthly_stake_limit": float(u.rg_monthly_stake_limit) if u.rg_monthly_stake_limit is not None else None,
            "self_excluded_until": u.rg_self_excluded_until.isoformat() if u.rg_self_excluded_until else None,
            "reality_check_minutes": u.rg_reality_check_minutes,
        },
        "entitlements": ent,
    }
