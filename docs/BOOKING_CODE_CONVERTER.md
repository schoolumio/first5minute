# Booking Code Converter

Moves a betslip from one bookmaker to another. **It never places bets and never invents booking codes.** A destination code is shown
only when the destination bookmaker (through a connected, legitimate integration) actually returned one.

URL: `/booking-code-converter` (nav label "Convert Booking Code"). Requires a signed-in, email-verified user (any plan). Self-excluded
users are blocked. API prefix: `/api/v1/booking-converter`.

## Status: which bookmakers work

| Bookmaker | Registered | Genuine conversion today |
|---|---|---|
| Bet9ja, SportyBet, BetKing, MSport, 1xBet, Betway, BetPawa | yes | **No - no integration connected** |
| Demo Book Alpha / Beta / Gamma | only with `BOOKING_CONVERTER_DEMO=true` (never production) | simulator only (codes start `DEMO-`, labelled) |

First5Minute has no official API access to any of the seven. This project deliberately does **not** use unofficial/undocumented endpoints or
scraping: they break without notice, can breach a bookmaker's terms, and are usually behind bot protection / CAPTCHAs, which we must not bypass.
In the UI these bookmakers show "not connected yet" and conversions that involve them stop with a clear message.

## How a conversion works

1. `POST /decode` `{code, source, destination}`: validates, reads the source slip via the source adapter -> normalised selections.
2. `POST /{id}/match`: finds each fixture at the destination and maps every selection to the destination's exact market + outcome.
3. `POST /{id}/generate` `{proceed_with_partial}`: asks the destination adapter for a real code (or returns the recreated slip as text when the
   destination cannot create codes). If anything could not be matched the user must confirm first (`409 needs_decision`).

State between steps is a short-lived, owner-bound server-side session (Redis, memory fallback; 15 min). History (`booking_conversions`) stores
counts and outcomes only - never codes or selections. Identical requests are de-duplicated (120 s) and generation is idempotent per session.

## Matching rules (never silently substitute)

* Event: both teams match (aliases, accents, FC/AC prefixes; Women/U21/B teams only match their own kind), kick-off within 30 min, same sport.
  Two plausible candidates -> `ambiguous_fixture`; reversed home/away -> `teams_reversed` (never swapped).
* Market: reduced to `(market, period, line, outcome)` and matched **exactly**. Supported: 1X2, Double Chance, Draw No Bet, BTTS, total goals
  Over/Under (single line), HT/FT, each for full time / 1st half / 2nd half where applicable. Over 2.5 never becomes Over 3.5; 1st half is never
  full time. Corners, cards, handicaps, combos, team totals, quarter lines are reported as unsupported.
* Every source selection yields exactly one result: `matched`, `odds_changed` (matched, destination odds differ), `unmatched` (+reason) or
  `unavailable` (+reason: market/line not offered, suspended, event started, lookup failed). Nothing is removed silently.

## Connecting a real bookmaker

You need an **official partner/API agreement** with that bookmaker (or a licensed aggregator) allowing: reading a booking code, searching
fixtures/markets/odds, and optionally creating a booking code. Then edit its stub in `backend/app/booking_converter/adapters/real.py`:

```python
class Bet9jaAdapter(BookmakerAdapter):
    code, name = "bet9ja", "Bet9ja"
    capabilities = Capabilities(can_decode=True, can_find_events=True, can_generate=True)   # only what the integration really supports
    def available(self): return bool(os.environ.get("BET9JA_API_KEY"))
    def decode(self, code) -> DecodedBetslip: ...            # -> Selection(...) list; raise BookingCodeNotFound for unknown/expired
    def find_events(self, query: EventQuery) -> list[DestEvent]: ...   # current fixtures with markets + odds
    def create_booking(self, picks: list[Pick]) -> GeneratedBooking: ...   # return the bookmaker's own code
```

Rules for adapters: read credentials from environment variables (never the frontend), set timeouts from
`settings.booking_converter_timeout_seconds`, raise `UpstreamError` on network problems, never log codes or credentials, and never bypass
authentication or CAPTCHAs. Add tests with mocked responses (see `tests/test_booking_converter.py`). The registry is
`adapters/registry.py`; adding another bookmaker is one new adapter class.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BOOKING_CONVERTER_ENABLED` | `true` | master switch (503 when off) |
| `BOOKING_CONVERTER_DEMO` | `false` | fictional demo bookmakers; refused in production |
| `BOOKING_CONVERTER_TIMEOUT_SECONDS` | `15` | per bookmaker request |
| `BOOKING_CONVERTER_PER_MINUTE` / `_PER_HOUR` | `8` / `60` | per-user rate limits on decode |

## Testing locally (demo mode, Windows cmd)

Set `BOOKING_CONVERTER_DEMO=true` in `.env`, run `alembic upgrade head`, start the API and website, sign in, open **Convert Booking Code**.
Demo codes (use Demo Book Alpha -> Demo Book Beta unless noted): `DEMOALL` (all convert, one odds change, a DEMO code), `DEMOPART`
(1 matched, others unmatched/unavailable, asks you to confirm), `DEMOMARKET` (unsupported market), `DEMOGENFAIL` (code creation fails),
`DEMOWOMEN` (women's fixture must not match the men's), `DEMOEXPIRED` (not found). Convert `DEMOALL` to **Demo Book Gamma** to see the
"recreate manually" path. Demo output is always labelled and is never a real bookmaker code.
