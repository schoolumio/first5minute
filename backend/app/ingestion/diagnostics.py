"""Cheap, read-only provider sanity check used before a real backfill (`python -m app.cli provider-check`).

It spends only a handful of requests: provider health, one day of fixtures (allowlisted leagues), and ONE finished fixture
with its event timeline - then verifies that the timeline reconciles with the final score and shows what the five-minute
engine would conclude. If this looks right, a backfill will work; if not, you find out before burning quota."""

from __future__ import annotations

from datetime import date, timedelta

from app.engine.settlement import GoalTiming, Rule, score_at_cutoff, timeline_consistent
from app.providers.football.base import FINAL_STATUSES, FootballDataProvider, NormalizedFixture, ProviderError


def _goal_timings(nf: NormalizedFixture) -> list[GoalTiming]:
    out = []
    for e in nf.events or []:
        if e.type != "goal" or e.team_provider_id is None:
            continue
        team_is_home = e.team_provider_id == nf.home_team.provider_id
        credited_home = (not team_is_home) if e.detail == "own_goal" else team_is_home
        out.append(GoalTiming(scoring_side="home" if credited_home else "away", period=e.period, minute=e.minute,
                              extra_minute=e.extra_minute, second=e.second, is_cancelled=e.is_cancelled,
                              is_own_goal=e.detail == "own_goal"))
    return out


def _describe_sample(provider: FootballDataProvider, sample: NormalizedFixture) -> dict:
    detail = provider.fixture_with_events(sample.provider_id)
    goals = _goal_timings(detail)
    consistent = timeline_consistent(goals, detail.home_score_ft, detail.away_score_ft)
    cut = score_at_cutoff(goals, Rule())
    return {
        "id": detail.provider_id, "match": f"{detail.home_team.name} vs {detail.away_team.name}", "competition": detail.competition.name,
        "final_score": f"{detail.home_score_ft}-{detail.away_score_ft}", "events_returned": len(detail.events or []),
        "goal_events": [f"{g.minute}{'+' + str(g.extra_minute) if g.extra_minute else ''}' {g.scoring_side}"
                        f"{' (own goal)' if g.is_own_goal else ''}{' (cancelled)' if g.is_cancelled else ''}" for g in goals],
        "timeline_reconciles_with_score": consistent,
        "score_at_5_minutes": f"{cut.home}-{cut.away}" if cut.resolved else f"unresolved ({cut.reason})",
        "has_second_precision": any(g.second is not None for g in goals),
    }


def _verdict(sample: dict) -> str:
    if sample["timeline_reconciles_with_score"]:
        return "OK: the timeline reconciles with the final score, so this competition can feed the model."
    return ("WARNING: goal events do NOT reconcile with the score for this fixture. If this is typical for the league, it has "
            "poor event coverage on your plan and will be excluded automatically.")


def check_provider(provider: FootballDataProvider, today: date, allow: set[str] | None, look_back_days: int = 3,
                   only_day: date | None = None) -> dict:
    """Probe recent days (or one explicit day). Provider errors are REPORTED, not raised, so the cause is visible."""
    report: dict = {"provider": provider.name, "health": _safe_health(provider),
                    "league_allowlist": sorted(allow) if allow else "all", "days": []}
    sample: NormalizedFixture | None = None
    offsets = [0] if only_day else list(range(0, look_back_days + 1))
    for offset in offsets:
        day = only_day or (today - timedelta(days=offset))
        try:
            fixtures = provider.fixtures_by_date(day)
        except ProviderError as exc:
            report["days"].append({"date": day.isoformat(), "error": str(exc)})
            continue
        kept = [f for f in fixtures if allow is None or f.competition.provider_id in allow]
        comps: dict[str, int] = {}
        for f in kept:
            key = f"{f.competition.provider_id}:{f.competition.name}"
            comps[key] = comps.get(key, 0) + 1
        finals = [f for f in kept if f.status in FINAL_STATUSES]
        report["days"].append({"date": day.isoformat(), "fixtures_all_leagues": len(fixtures), "fixtures_in_allowlist": len(kept),
                               "finished": len(finals), "competitions": comps})
        if finals and sample is None:
            sample = finals[0]
        if sample is not None and offset >= 1:
            break
    if sample is None:
        errors = [d for d in report["days"] if "error" in d]
        if errors and len(errors) == len(report["days"]):
            report["verdict"] = ("Every request was refused: " + errors[0]["error"] + "  -> If this mentions your plan, try an "
                                 "older season instead: python -m app.cli provider-check --league <id> --season <year>")
        else:
            report["verdict"] = ("No finished fixtures found for your leagues in these days (off-season or wrong league ids?). Check "
                                 "FOOTBALL_LEAGUE_IDS with `python -m app.cli leagues --search <name>`, or probe a season: "
                                 "python -m app.cli provider-check --league <id> --season <year>")
        return report
    try:
        report["sample_fixture"] = _describe_sample(provider, sample)
        report["verdict"] = _verdict(report["sample_fixture"])
    except ProviderError as exc:
        report["verdict"] = f"Could not fetch the event timeline: {exc}"
    return report


def check_season(provider: FootballDataProvider, league_id: str, season: int) -> dict:
    """Probe one league-season: 1 request for the fixture list + 1 for a sample timeline."""
    report: dict = {"provider": provider.name, "health": _safe_health(provider), "league": league_id, "season": season}
    try:
        fixtures = provider.fixtures_by_league_season(league_id, season)
    except ProviderError as exc:
        report["verdict"] = f"Request refused: {exc}"
        return report
    finals = [f for f in fixtures if f.status in FINAL_STATUSES]
    report["fixtures_in_season"] = len(fixtures)
    report["finished"] = len(finals)
    report["competition"] = fixtures[0].competition.name if fixtures else None
    report["requests_to_download_if_plan_allows_bulk"] = 1 + -(-len(finals) // 20)
    report["requests_to_download_if_one_per_match"] = 1 + len(finals)      # free plans refuse bulk requests
    if not finals:
        report["verdict"] = "No finished fixtures returned for that league and season (check the ids/year)."
        return report
    try:
        report["sample_fixture"] = _describe_sample(provider, finals[len(finals) // 2])
        report["verdict"] = _verdict(report["sample_fixture"])
    except ProviderError as exc:
        report["verdict"] = f"Could not fetch the event timeline: {exc}"
    return report


def _safe_health(provider: FootballDataProvider) -> dict:
    try:
        return provider.health_check()
    except ProviderError as exc:
        return {"provider": provider.name, "ok": False, "error": str(exc)}
