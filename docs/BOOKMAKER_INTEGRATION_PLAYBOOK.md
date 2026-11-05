# How to get bookmakers integrated (playbook)

Goal: for each bookmaker, an **official, written permission and technical access** that lets First5Minute (1) create a booking code for the
games a player picked, and ideally (2) read prices so the ticket can show that bookmaker's own odds and the edge against the model.
The software side is finished and waiting (`backend/app/booking_converter/adapters/real.py`, one adapter per bookmaker). What is missing is
the agreement and the documentation. This document is how you get them.

## 1. What I found (research of 2026-11-05, so you plan on facts)

* **No public booking-code API found** for Bet9ja, SportyBet, BetKing or MSport. A third-party marketplace listing says SportyBet publishes no
  official developer API and sells an **unofficial** endpoint; we do not use that kind of thing (it breaks, can breach the bookmaker's terms, and
  would put your business at risk). ([listing](https://parse.bot/marketplace/b0c4782f-8591-441b-92ee-6cf4b190317b/sportybet-com-ng-api))
* **Affiliate programmes exist** and are the realistic door in: Bet9ja has one (sign-up reported at webaffiliates.bet9ja.com; verify the address
  yourself) ([guide](https://statsdrone.com/affiliate-programs/bet9ja-affiliates/)); SportyBet has one ([article](https://charmed-reading-add.notion.site/Unlocking-the-Potential-of-Gambling-Affiliate-Marketing-A-Deep-Dive-into-the-SportyBet-Affiliate-Pr-1427ceccfd0c8097bd6cff4620cf116e));
  1xBet runs **1xPartners** with RevShare, CPA and hybrid models, and an account-level API token for **tracking and reporting**
  ([Routy help](https://support.routy.app/hc/en-us/articles/19000213788049), [news](https://sportsbettingoperator.com/news/1xbet-wins-best-affiliate-program-at-sbc-awards-malta-as-1xpartners-hits-500000-partners-milestone/)).
  I found nothing saying those partner APIs can create bet slips or booking codes: that is the question to put to each account manager.
* Converter products already exist in the market (for example [AccuratePredict's free converter](https://www.thisdaylive.com/2025/08/17/accuratepredict-unveils-africas-first-free-bet-slip-converter-for-punters))
  but nothing I found says how they get bookmaker access. Do not assume they have official deals, and do not copy unknown methods.
* Booking codes are specific to each bookmaker and a converter has to rebuild the same selections on the destination, so each bookmaker needs
  its own integration ([explainer](https://owngoalnigeria.com/2026/05/28/bet9ja-to-sportybet-code-conversion-the-complete-step-by-step-guide-for-2026/)).
* Nothing I found names MSport or BetKing sportsbook partner contacts, or covers BetPawa and Betway for Nigeria. Treat every bookmaker as "ask".

Honest conclusion: you will get access only through a **commercial relationship**, probably starting as an affiliate/partner and escalating to a
technical agreement. Plan for weeks to months per bookmaker, and do not make launch depend on any single one.

## 2. The make-or-break question: do they even list five-minute markets?

Your picks are "no goal 0-5'" and "level at 5'". A booking code can only contain markets that bookmaker actually offers. If a bookmaker has no
five-minute market, there is nothing to put on its slip, and First5Minute will (correctly) refuse to substitute a different one (a "first 10
minutes" market settles differently and is **not** equivalent). So the first question to every bookmaker, before any technical talk:

> "Which markets do you list for the first 5 minutes of a match (no goal by 5:00 / score level at 5:00), for which leagues, pre-match? How do
> you define the 5-minute cut-off and settle it?"

Check this yourself too by browsing each bookmaker's football markets for a big league fixture. If a bookmaker does not list them, the pitch
changes: you are offering them a reason to **add** the market (your users are asking for it), or you integrate only the markets they do have.

## 3. Your pitch: what is in it for the bookmaker

* New and returning players arriving **with a ready-made slip** on *their* platform (higher intent; code placed on their site/app).
* Attributable traffic: every code created through you can carry the partner tracking they already use (affiliate IDs, sub-IDs).
* You never place bets, never hold funds, never ask for player passwords; you are 18+ and responsible-gambling by design.
* Demand evidence: your user numbers, the scanner's engagement, and a live demo (your Vercel link, labelled demo data).

## 4. Prepare the package (week 0)

* One-page brief (who you are, product, the five-minute markets, the player journey: pick games > choose bookmaker > get a code > place it
  yourself), a 2-minute screen recording of the demo flow, your safety statement (no bets, no funds, no credentials, 18+), company details
  (registered business, contact person), and a statement of expected volume (be modest and honest).
* The legal opinion from `docs/LAUNCH_REQUIREMENTS.md` section 7, or at least a note that it is under way.
* A shared email address (partnerships@yourdomain) and a tracking sheet: bookmaker, contact, date, status, next step.

## 5. Outreach sequence (per bookmaker)

1. **Register as an affiliate/partner** where a programme exists (Bet9ja, SportyBet, 1xPartners and similar). This gets you an **account
   manager**, which is the human who can route a technical request. Use your real company details. Do not sign up under false pretences.
2. **Message the account manager** (template below). Also find the bookmaker's partnerships/B2B or business-development contact through
   its website footer, official LinkedIn page and industry events (Nigerian and African gaming events are where these teams meet partners).
3. **Follow up** every 5 working days, with a different angle each time (a demo link, a screenshot of a booked ticket, a usage number).
4. **First call agenda (30 minutes):** who you are; the five-minute markets question (section 2); what the technical route could be; commercial
   model (revenue share or CPA on referred customers, any minimum, exclusivity); timelines.
5. **Written agreement before any work.** Do not start building against anything that is not in writing.

Template (email):

> Subject: Partnership request: official booking-code integration for First5Minute
>
> Hello [Name], I run First5Minute, a football analytics service focused on the first five minutes of a match. Players choose games from our
> scanner and want to load exactly those selections on their own [Bookmaker] account. We never place bets, hold funds or ask for player
> credentials; we are 18+ and publish clear responsible-gambling notices. Could we speak about an official route that lets us (1) create a
> booking code for the selections a player picks, and (2) read the markets and odds you offer, ideally with a sandbox? We would also like to
> understand which five-minute markets you list. A short demo is here: [link]. Which team should we speak to? Thank you, [Name, role, phone].

## 6. What to ask for (the technical checklist, mapped to the adapter)

| Need | Adapter method | Questions for the bookmaker |
|---|---|---|
| Create a booking code | `create_booking` | Is there an endpoint to build a slip and get a code? Does the code expire? Can the player load it in app and website? |
| Find the fixtures and markets | `find_events` | Fixture search with team names, kick-off time and league? Market and outcome identifiers? Odds per outcome? |
| Read a player's code (only for the code-conversion screen) | `decode` | Is there an endpoint to read a code's selections? |
| Access | all | Sandbox and production credentials, authentication method, IP allow-listing, rate limits, uptime/SLA |
| Rules | all | May a third party create codes for its users? Branding and attribution rules; data retention limits; responsible-gambling requirements |
| Five-minute markets | all | Section 2. Identifiers, cut-off rule, settlement rule |
| Support | all | A technical contact and an incident route |

Red flags: anyone offering "unofficial endpoints", scrapers, shared logins or ways round CAPTCHAs or bot protection. Decline. Also decline any
arrangement where players give you their bookmaker password.

## 7. Contract points to read carefully (have your lawyer check)

Fees or revenue share and how attributed; minimum volumes; exclusivity (never give a bookmaker exclusivity at the start); permitted
use of their data and brand; liability if odds or markets shown are wrong; responsible-gambling and age rules; termination and notice; data
protection and where data is processed; what happens to codes already created if the deal ends.

## 8. Build and go-live (after the agreement; about days to a couple of weeks of developer time each)

1. Get sandbox credentials and the documentation. Send them to me (credentials only through the host's environment form, never in chat).
2. Fill in that bookmaker's adapter methods in `real.py`; set `capabilities` to exactly what the integration supports; read credentials from
   environment variables; map its market ids to the canonical markets (including the five-minute ones, in `canonical.py`).
3. Add tests with mocked responses; run the suite (`tests/test_booking_converter.py`).
4. Test in the sandbox: a ticket with one, three and ten games; a game the bookmaker lacks; a price change between match and generate; an
   outage. The app already reports each case rather than guessing.
5. Production credentials in Render's environment; `BOOKING_CONVERTER_DEMO=false`; `python -m app.cli doctor`; pilot with a few real users
   and real money kept small; compare the booked slip on the bookmaker with what the app showed.
6. Go live for that bookmaker only. Repeat for the next.

## 9. Order of approach and fallbacks

* Start with the two or three bookmakers your users use most, in parallel; the long wait is the agreement, not the code.
* **While you wait:** launch with those bookmakers shown as "not connected yet". Consider the "Copy ticket as text" fallback
  (not built yet; small change). Where an affiliate deal exists, a plain outbound link to the bookmaker (no code) is possible; the app
  never pretends it made a code.
* **If a bookmaker refuses or goes quiet:** do not use unofficial methods. Ask whether it uses a sportsbook-platform supplier that offers
  partner access, or park that bookmaker.

## 10. Cost to budget

No fee is published anywhere I could find: it is whatever the bookmaker offers (revenue share, CPA, or a fixed fee). Budget for: your time
(or a part-time business-development person), a lawyer's review of each agreement, developer time per integration, and the possibility that
the commercial terms include minimum volumes. Ask for the terms in writing before spending on development.
