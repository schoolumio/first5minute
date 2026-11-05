"""Team-name comparison for matching the same fixture across bookmakers.

Deliberately conservative: a pair of names only matches when they are, after normalisation and alias expansion, the same
club (or one is the other with extra words, like "Inter" / "Inter Milan"). Youth/women/reserve markers must agree, so
"Arsenal" never matches "Arsenal Women" or "Arsenal U21".
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache

from app.booking_converter.canonical import norm_name

GENERIC = {"fc", "cf", "sc", "afc", "fk", "sk", "cd", "ud", "ac", "as", "ssc", "ss", "sv", "bk", "ik", "if", "club", "the",
           "calcio", "de", "1"}
QUALIFIERS = {"w", "women", "womens", "ladies", "ii", "iii", "b", "reserves", "res", "youth"}
_QUAL_RE = re.compile(r"^u\d{2}$")

TOKEN_EXPANSION = {"utd": "united", "intl": "international", "dep": "deportivo", "ath": "athletic", "atl": "atletico",
                   "st": "saint", "mgladbach": "monchengladbach", "munchen": "munich",
                   "women": "w", "womens": "w", "ladies": "w"}

# normalised variant -> normalised canonical form. Extend freely; lookups are exact on the whole name.
ALIASES = {
    "man utd": "manchester united", "man united": "manchester united", "man city": "manchester city",
    "spurs": "tottenham", "tottenham hotspur": "tottenham", "wolves": "wolverhampton wanderers", "wolverhampton": "wolverhampton wanderers",
    "newcastle": "newcastle united", "west ham": "west ham united", "nottm forest": "nottingham forest", "forest": "nottingham forest",
    "brighton and hove albion": "brighton", "leeds": "leeds united", "leicester": "leicester city", "norwich": "norwich city",
    "psg": "paris saint germain", "paris sg": "paris saint germain", "paris saint germain": "paris saint germain",
    "bayern": "bayern munich", "bayern munchen": "bayern munich", "inter": "inter milan", "internazionale": "inter milan",
    "atletico": "atletico madrid", "atl madrid": "atletico madrid", "athletic club": "athletic bilbao",
    "dortmund": "borussia dortmund", "gladbach": "monchengladbach", "borussia monchengladbach": "monchengladbach",
    "b monchengladbach": "monchengladbach", "leverkusen": "bayer leverkusen", "leipzig": "rb leipzig",
    "sporting cp": "sporting lisbon", "sporting": "sporting lisbon", "porto": "fc porto", "benfica": "sl benfica",
    "ac milan": "acmilan", "milan": "acmilan", "a c milan": "acmilan",
    "ajax amsterdam": "ajax", "juve": "juventus", "napoli": "napoli", "roma": "roma", "lazio": "lazio",
    "real sociedad": "real sociedad", "betis": "real betis", "celta vigo": "celta", "celta de vigo": "celta",
    "kano pillars": "kano pillars", "enyimba": "enyimba", "rangers intl": "rangers international",
}


SUBSET_SIMILARITY = 0.88   # below the normal match threshold (0.90): see matcher.match_event


@lru_cache(maxsize=4096)
def canonical_team(name: str) -> tuple[frozenset[str], frozenset[str]]:
    """(core tokens, qualifier tokens) of a team name."""
    n = norm_name(name)
    n = ALIASES.get(n, n)
    tokens = [TOKEN_EXPANSION.get(t, t) for t in n.split()]
    n2 = ALIASES.get(" ".join(tokens), " ".join(tokens))
    tokens = n2.split()
    quals = {t for t in tokens if t in QUALIFIERS or _QUAL_RE.match(t)}
    core = [t for t in tokens if t not in quals and t not in GENERIC]
    return frozenset(core), frozenset(quals)


def team_similarity(a: str, b: str) -> float:
    """0.0-1.0. 1.0 = same club after normalisation; <0.9 is never treated as the same team."""
    (ca, qa), (cb, qb) = canonical_team(a), canonical_team(b)
    if not ca or not cb or qa != qb:
        return 0.0
    if ca == cb:
        return 1.0
    sa, sb = " ".join(sorted(ca)), " ".join(sorted(cb))
    ratio = SequenceMatcher(None, sa, sb).ratio()
    if ca < cb or cb < ca:                  # "madrid" vs "real madrid": plausible, but only with strong supporting evidence
        ratio = max(ratio, SUBSET_SIMILARITY)
    return round(ratio, 4)
