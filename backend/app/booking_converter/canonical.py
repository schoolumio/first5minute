"""Canonical betting-market model.

Bookmakers name the same market differently ("GG/NG", "Both Teams To Score", market id 29 ...). To compare a source
selection with a destination selection we reduce both to ``Canon(market, period, line, outcome)`` and require an EXACT
match. A market we cannot reduce with certainty (corners, cards, handicaps, combos, team totals, quarter lines ...)
is reported as unsupported; the converter never "approximates" a market.

Supported (football only): 1X2, Double Chance, Draw No Bet, Both Teams To Score, Total Goals Over/Under (any single
line), and Half Time/Full Time. Match-result style markets may be for the full match or the 1st / 2nd half.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

FT, H1, H2 = "FT", "1H", "2H"

M_1X2, M_DC, M_DNB, M_BTTS, M_OU, M_HTFT = "1X2", "DOUBLE_CHANCE", "DRAW_NO_BET", "BTTS", "OVER_UNDER", "HT_FT"

MARKET_LABELS = {M_1X2: "1X2", M_DC: "Double chance", M_DNB: "Draw no bet", M_BTTS: "Both teams to score",
                 M_OU: "Total goals over/under", M_HTFT: "Half time / full time"}
PERIOD_LABELS = {FT: "Full time", H1: "1st half", H2: "2nd half"}


@dataclass(frozen=True)
class Canon:
    market: str
    period: str
    line: Decimal | None
    outcome: str

    def market_key(self) -> tuple[str, str]:
        return (self.market, self.period)

    def describe(self) -> str:
        bits = [MARKET_LABELS.get(self.market, self.market)]
        if self.period != FT:
            bits.append(f"({PERIOD_LABELS[self.period]})")
        if self.line is not None:
            bits.append(str(self.line.normalize()))
        return " ".join(bits) + f": {self.outcome}"


@dataclass(frozen=True)
class CanonResult:
    canon: Canon | None
    reason: str | None = None       # why it is unsupported (user-facing)


def norm_text(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9&/+.,\- ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_name(s: str | None) -> str:
    """Team-name normalisation: lower case, no accents or punctuation."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _unsupported(reason: str) -> CanonResult:
    return CanonResult(None, reason)


_COMBO = re.compile(r"&|\band\b|\+|\bcombo\b|\bcombination\b")
_UNSUPPORTED_WORDS = re.compile(
    r"\bcorners?\b|\bcards?\b|\bbookings?\b|\boffsides?\b|\bshots?\b|\bthrow|\bpenalt|\bfouls?\b|\bscorers?\b|\bgoalscorers?\b|"
    r"\bassists?\b|\bminutes?\b|\bgoal ?kicks?\b|\bclean sheet\b|\bwin to nil\b|\bexact\b|\bcorrect score\b|\bhandicaps?\b|"
    r"\bhcp\b|\basian\b|\bodd\b|\beven\b|\bfirst goal\b|\blast goal\b|\bnext goal\b|\binterval\b|\beither half\b|"
    r"\bboth halves\b|\bhighest scoring\b|\brace to\b|\bto qualify\b|\bto advance\b|\bplayers?\b|\bmargin\b|\bto score\b")
_QUARTER = re.compile(r"\d\s*[/,]\s*\d+(?:\.\d+)?\s*(?:$|\s)|\d\.?\d*\s*/\s*\d")


def _period(name: str) -> str:
    if re.search(r"\b(2nd|second)\s+half\b|\b2h\b|\bsecond-half\b", name):
        return H2
    if re.search(r"\b(1st|first)\s+half\b|\b1h\b|\bhalf ?time\b|\bht\b", name):
        return H1
    return FT


def _strip_period_and_filler(name: str) -> str:
    n = re.sub(r"\b(1st|first|2nd|second)\s+half\b|\b[12]h\b|\bhalf ?time\b|\bht\b", " ", name)
    n = re.sub(r"\b(full ?time|ft|regular time|reg time|90 min(ute)?s?|match|ordinary time|incl\.? overtime)\b", " ", n)
    n = re.sub(r"[-()]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _side(out: str, home: str | None, away: str | None) -> str | None:
    """Map an outcome label to HOME / DRAW / AWAY (team names count as HOME / AWAY)."""
    o = norm_text(out)
    h, a = norm_text(home), norm_text(away)
    if h and o == h:
        return "HOME"
    if a and o == a:
        return "AWAY"
    if o in {"1", "home", "home win", "home team", "h", "w1", "team 1"}:
        return "HOME"
    if o in {"x", "draw", "d", "tie"}:
        return "DRAW"
    if o in {"2", "away", "away win", "away team", "a", "w2", "team 2"}:
        return "AWAY"
    return None


def _dc_outcome(out: str, home: str | None, away: str | None) -> str | None:
    o = norm_text(out)
    for team, token in sorted(((norm_text(home), "home"), (norm_text(away), "away")), key=lambda t: -len(t[0])):
        if team:
            o = o.replace(team, token)
    o = re.sub(r"\s*(/|-|,|\bor\b)\s*", " or ", o)
    o = re.sub(r"\s+", " ", o).strip()
    if o in {"1x", "home or draw", "draw or home", "1 or x", "x or 1", "home draw", "draw home"}:
        return "1X"
    if o in {"x2", "draw or away", "away or draw", "x or 2", "2 or x", "draw away", "away draw"}:
        return "X2"
    if o in {"12", "home or away", "away or home", "1 or 2", "2 or 1", "home away", "away home"}:
        return "12"
    return None


def _parse_line(text: str | None) -> Decimal | None:
    if not text:
        return None
    m = re.search(r"(?<![\d.])(\d+(?:[.,]\d+)?)(?![\d.])", text)
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:  # pragma: no cover - regex guarantees a number
        return None


def _totals(name: str, out: str, specifier: str | None, period: str) -> CanonResult:
    if re.search(r"\b(home|away|team|1st team|2nd team)\b", name):
        return _unsupported("Team totals are not supported yet.")
    o = norm_text(out)
    m = re.match(r"^(over|under|o|u)\b\s*[-:=]?\s*(.*)$", o)
    if not m:
        return _unsupported(f"Outcome “{out}” is not an over/under pick.")
    side = "OVER" if m.group(1) in ("over", "o") else "UNDER"
    spec = norm_text(specifier)
    texts = [m.group(2), spec]
    name_line = re.search(r"(?:over|under|total|o ?/ ?u|goals?)\D{0,14}?(\d+(?:[.,]\d+)?)(?![\d])", name)
    if name_line:
        texts.append(name_line.group(1))
    if any(t and _QUARTER.search(t) for t in texts):
        return _unsupported("Split (quarter) lines such as 2.5/3 are not supported yet.")
    lines = {ln for ln in (_parse_line(t) for t in texts) if ln is not None}
    if not lines:
        return _unsupported("The goals line (for example 2.5) could not be read.")
    if len(lines) > 1:
        return _unsupported("The bookmaker reported conflicting goals lines.")
    return CanonResult(Canon(M_OU, period, lines.pop(), side))


def canonicalize(market_name: str, outcome: str, specifier: str | None = None, home: str | None = None,
                 away: str | None = None) -> CanonResult:
    name = norm_text(market_name)
    out = norm_text(outcome)
    if not name or not out:
        return _unsupported("The market or outcome name is missing.")
    if _COMBO.search(name) or re.search(r"&|\band\b|\+", out):
        return _unsupported("Combined (multi-part) markets are not supported yet.")
    period = _period(name)

    if re.search(r"half ?time ?/ ?full ?time|\bht ?/ ?ft\b|\bht ?ft\b|\bhalf-?time/full-?time\b", name):
        parts = [p for p in re.split(r"\s*(?:/|-)\s*", out) if p]
        sides = [_side(p, home, away) for p in parts]
        if len(parts) != 2 or any(s is None for s in sides):
            return _unsupported(f"Outcome “{outcome}” is not a half time/full time pick.")
        sym = {"HOME": "1", "DRAW": "X", "AWAY": "2"}
        return CanonResult(Canon(M_HTFT, FT, None, f"{sym[sides[0]]}/{sym[sides[1]]}"))
    if re.search(r"\bdouble chance\b|\bdc\b", name):
        o = _dc_outcome(out, home, away)
        return CanonResult(Canon(M_DC, period, None, o)) if o else _unsupported(f"Outcome “{outcome}” is not a double chance pick.")
    if re.search(r"\bdraw no bet\b|\bdnb\b", name):
        s = _side(out, home, away)
        return CanonResult(Canon(M_DNB, period, None, s)) if s in ("HOME", "AWAY") else \
            _unsupported(f"Outcome “{outcome}” is not a draw-no-bet pick.")
    if re.search(r"both teams (to )?score|\bbtts\b|\bgg ?/ ?ng\b|\bgg\b|\bng\b", name):
        if out in {"yes", "gg", "y"}:
            return CanonResult(Canon(M_BTTS, period, None, "YES"))
        if out in {"no", "ng", "n"}:
            return CanonResult(Canon(M_BTTS, period, None, "NO"))
        return _unsupported(f"Outcome “{outcome}” is not a both-teams-to-score pick.")
    if _UNSUPPORTED_WORDS.search(name):
        return _unsupported("This market type (for example corners, cards, handicaps or exact scores) is not supported yet.")
    if re.search(r"over ?/ ?under|under ?/ ?over|\bo ?/ ?u\b|\btotals?\b|goals? over|\bgoals? (?:under|over)\b", name):
        return _totals(name, outcome, specifier, period)
    if _strip_period_and_filler(name) in {"1x2", "result", "winner", "3 way", "three way", "3way", "1x2 result", "result 1x2",
                                          "1 x 2", "moneyline", "match winner", "winner 1x2"}:
        s = _side(out, home, away)
        return CanonResult(Canon(M_1X2, period, None, s)) if s else _unsupported(f"Outcome “{outcome}” is not a 1X2 pick.")
    return _unsupported("This market type is not supported yet.")
