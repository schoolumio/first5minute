import Link from "next/link";
import { ArrowRight, BarChart3, Bell, Database, Gauge, Lock, Radar, Scale, ShieldCheck, Ticket } from "lucide-react";
import { KickoffDial } from "@/components/marketing/kickoff-dial";
import { PricingTable } from "@/components/pricing-table";
import { ButtonLink } from "@/components/ui/button";

const STEPS = [
  { t: "Collect", b: "Upcoming fixtures across men's, women's, domestic, continental and international football, synchronised from licensed data providers." },
  { t: "Rebuild", b: "Timestamped goal events reconstruct the score at the exact cut-off, handling own goals, VAR cancellations and stoppage time." },
  { t: "Model", b: "Smoothed early-scoring and early-conceding rates feed two separate Poisson models that only see information available before kick-off." },
  { t: "Rank", b: "Matches are ranked by estimated probability, sample size and data quality, then marked Qualified, Watchlist or Excluded." },
];

const FAQ = [
  { q: "Is this a guaranteed betting system?", a: "No. First5Minute produces statistical estimates. Five-minute markets are low-scoring and noisy; even well-calibrated probabilities lose regularly. We never advertise guaranteed winnings or accuracy." },
  { q: "What exactly is the five-minute cutoff?", a: "By default the window is 00:00-04:59 of match time, measured from the actual kick-off. Bookmakers differ, so settlement rules are configurable, and goals whose timestamps are too imprecise to place relative to the cutoff are marked unresolved rather than guessed." },
  { q: "What is the difference between the two markets?", a: "Market A wins only if no goal is scored before the cutoff (0-0). Market B wins if the score is level at the cutoff, so 0-0, 1-1 and 2-2 all count. They are modelled and reported separately." },
  { q: "Why are some matches excluded?", a: "We never assign a qualifying prediction to a fixture without enough reliable, timestamped history. Competitions with poor event coverage are flagged and excluded rather than padded with assumptions." },
  { q: "Do you place bets or hold my money?", a: "No. First5Minute never holds funds, never places bets and never asks for sportsbook passwords. You pick games, we build the ticket and, where a bookmaker is connected, a booking code you place yourself." },
  { q: "How do I pay?", a: "Paid plans are billed monthly in Naira through Paystack, which accepts Nigerian cards, bank transfers, USSD and international cards. You can cancel anytime." },
];

const SAMPLE = [
  { h: "Ashford Rovers", a: "Calder City", c: "Demo Premier Division", pa: 91.2, pb: 90.8, tier: "Qualified" },
  { h: "Glenrock Union", a: "Oakfield Town", c: "Demo Liga Norte", pa: 90.3, pb: 89.9, tier: "Qualified" },
  { h: "Kingsport Women", a: "Lakeside Women", c: "Demo Women's Super League", pa: 88.4, pb: 88.0, tier: "Watchlist" },
];

function Console() {
  return (
    <div className="panel relative overflow-hidden rounded-[var(--radius-xl)] p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase tracking-[0.2em] text-muted">Opening-minute console</p>
        <span className="rounded-[4px] border border-demo/40 bg-demo/10 px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-[9px] font-semibold uppercase tracking-wider text-demo">Illustrative · fictional teams</span>
      </div>
      <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-center">
        <KickoffDial size={190} />
        <div className="w-full min-w-0 flex-1">
          <p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-[0.18em] text-subtle">Ashford Rovers vs Calder City</p>
          <div className="mt-2 grid grid-cols-2 gap-3">
            <div className="rounded-[var(--radius-md)] border border-brand-500/40 bg-brand-500/10 p-3">
              <p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-brand-300">No goal 0-5&apos;</p>
              <p className="numeral mt-1 text-[40px] leading-none">91.2<span className="text-xl text-muted">%</span></p>
            </div>
            <div className="rounded-[var(--radius-md)] border border-info/40 bg-info/10 p-3">
              <p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-info">Level at 5&apos;</p>
              <p className="numeral mt-1 text-[40px] leading-none">90.8<span className="text-xl text-muted">%</span></p>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-subtle">Model estimates with a confidence and data-quality grade, never a promise.</p>
        </div>
      </div>
      <ul className="mt-5 divide-y divide-border/70 border-t border-border/70">
        {SAMPLE.map((r) => (
          <li key={r.h} className="flex items-center justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <p className="truncate text-[13px] font-semibold">{r.h} <span className="font-normal text-muted">vs</span> {r.a}</p>
              <p className="truncate text-[11px] text-subtle">{r.c}</p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className={`font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase ${r.tier === "Qualified" ? "text-brand-400" : "text-info"}`}>{r.tier}</span>
              <span className="numeral w-14 text-right text-lg">{r.pa.toFixed(1)}%</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <span className="eyebrow">{children}</span>;
}
function H2({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <h2 className={`mt-4 font-[family-name:var(--font-display)] text-[34px] font-semibold uppercase leading-[1.05] tracking-wide sm:text-5xl ${className}`}>{children}</h2>;
}

function SettleStrip() {
  const cases = [
    { score: "0 - 0", a: true, b: true, note: "Nothing by the cut-off" },
    { score: "1 - 1", a: false, b: true, note: "Goals each, level" },
    { score: "1 - 0", a: false, b: false, note: "One goal, not level" },
    { score: "2 - 2", a: false, b: true, note: "Four early goals, level" },
  ];
  return (
    <div className="panel rounded-[var(--radius-xl)] p-5 sm:p-8">
      <div className="relative mt-2 mb-8">
        <div className="h-[3px] rounded bg-surface-4" />
        <div className="absolute inset-y-0 left-0 h-[3px] w-full rounded bg-gradient-to-r from-brand-500 via-brand-500 to-transparent" />
        {[["0:00", "0%", "Kick-off"], ["4:59", "88%", "Last second counted"], ["5:00", "100%", "Cut-off"]].map(([t, left, l]) => (
          <div key={t} className="absolute -top-[5px] flex -translate-x-1/2 flex-col items-center" style={{ left: left as string }}>
            <span className="h-3 w-3 rounded-full border-2 border-brand-500 bg-bg" />
            <span className="numeral mt-2 text-sm">{t}</span>
            <span className="hidden text-[10px] uppercase tracking-wider text-subtle sm:block">{l}</span>
          </div>
        ))}
      </div>
      <div className="mt-14 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cases.map((c) => (
          <div key={c.score} className="rounded-[var(--radius-md)] border border-border bg-bg/40 p-4">
            <p className="numeral text-3xl tracking-widest">{c.score}</p>
            <p className="mt-1 text-xs text-subtle">{c.note}</p>
            <div className="mt-3 flex gap-2">
              <span className={`rounded-[4px] px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase ${c.a ? "bg-brand-500/15 text-brand-300" : "bg-surface-3 text-subtle line-through"}`}>A · no goal</span>
              <span className={`rounded-[4px] px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase ${c.b ? "bg-info/15 text-info" : "bg-surface-3 text-subtle line-through"}`}>B · level</span>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-subtle">Scores at the cut-off, and which market each would settle (default window 00:00-04:59). Bookmakers differ: always read their rules.</p>
    </div>
  );
}

export default function LandingPage() {
  return (
    <>
      {/* HERO */}
      <section className="bg-stadium pitch-lines relative overflow-hidden border-b border-border">
        <div className="mx-auto grid max-w-7xl items-center gap-12 px-4 pb-20 pt-14 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:pb-28 lg:pt-24">
          <div>
            <Eyebrow>Football intelligence · five-minute markets</Eyebrow>
            <h1 className="mt-6 font-[family-name:var(--font-display)] text-[58px] font-bold uppercase leading-[0.95] tracking-wide sm:text-[88px] lg:text-[104px]">
              The first<br />five minutes.<br /><span className="text-brand-500">Decoded.</span>
            </h1>
            <p className="mt-7 max-w-xl text-lg leading-relaxed text-muted">
              We rebuild how thousands of matches actually opened, then estimate the chance of no goal, or a level score, at the five-minute
              cut-off. Every number comes with its sample size and data quality. No hype, no guarantees.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <ButtonLink href="/register" size="lg">Start free <ArrowRight className="h-4 w-4" aria-hidden /></ButtonLink>
              <ButtonLink href="#how-it-works" size="lg" variant="outline">See how it works</ButtonLink>
            </div>
            <ul className="mt-10 grid max-w-xl gap-3 text-sm text-muted sm:grid-cols-3">
              {[[Lock, "Locked before kick-off"], [ShieldCheck, "Uncalibrated until proven"], [Scale, "We never place bets"]].map(([Icon, t]) => {
                const I = Icon as typeof Lock;
                return <li key={t as string} className="flex items-center gap-2"><I className="h-4 w-4 shrink-0 text-brand-400" aria-hidden />{t as string}</li>;
              })}
            </ul>
            <p className="mt-6 text-xs text-subtle">18+ only. Statistical estimates, not guarantees.</p>
          </div>
          <Console />
        </div>
      </section>

      {/* HOW A FIVE-MINUTE MARKET SETTLES */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6">
        <div className="max-w-3xl">
          <Eyebrow>The market</Eyebrow>
          <H2>Five minutes. Two ways to win.</H2>
          <p className="mt-4 text-muted">The score at the cut-off decides everything. Market A wins on 0-0. Market B wins on any level score. We model them separately because they behave differently.</p>
        </div>
        <div className="mt-10"><SettleStrip /></div>
      </section>

      {/* PIPELINE */}
      <section id="how-it-works" className="scroll-mt-20 border-y border-border bg-surface/30">
        <div className="mx-auto max-w-7xl px-4 py-24 sm:px-6">
          <Eyebrow>How it works</Eyebrow>
          <H2>From raw fixtures to ranked matches</H2>
          <ol className="relative mt-14 grid gap-10 md:grid-cols-4 md:gap-6">
            <span className="absolute left-[18px] top-2 hidden h-[2px] w-[calc(100%-36px)] bg-gradient-to-r from-brand-500 via-surface-4 to-surface-4 md:block" aria-hidden />
            {STEPS.map((s, i) => (
              <li key={s.t} className="relative pl-12 md:pl-0 md:pt-12">
                <span className="numeral absolute left-0 top-0 flex h-9 w-9 items-center justify-center rounded-full border-2 border-brand-500 bg-bg text-lg text-brand-300">{i + 1}</span>
                <h3 className="font-[family-name:var(--font-display)] text-2xl font-semibold uppercase tracking-wide">{s.t}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{s.b}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* TWO MODELS */}
      <section id="markets" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-24 sm:px-6">
        <Eyebrow>Two markets, two models</Eyebrow>
        <H2>Kept strictly separate</H2>
        <div className="mt-12 grid gap-5 lg:grid-cols-2">
          {[
            { tag: "Market A", tone: "brand", title: "No goal in the first five minutes", body: "Wins only if the score is 0-0 at the cut-off. Expected early goals for each side combine attacking and defensive strengths with the competition baseline.", formula: "P(no goal) = e^-(λhome + λaway)", big: "0 - 0" },
            { tag: "Market B", tone: "info", title: "Level at five minutes", body: "Wins if the scores are equal at the cut-off: 0-0, 1-1, 2-2 or any level score, computed from separate home and away early-goal distributions.", formula: "P(level) = Σk P(H=k)·P(A=k)", big: "k - k" },
          ].map((m) => (
            <div key={m.tag} className="panel relative overflow-hidden rounded-[var(--radius-xl)] p-7 sm:p-9">
              <span className={`numeral pointer-events-none absolute -right-2 -top-4 text-[120px] leading-none tracking-widest ${m.tone === "brand" ? "text-brand-500/[0.07]" : "text-info/[0.08]"}`} aria-hidden>{m.big}</span>
              <span className={`font-[family-name:var(--font-mono)] text-[11px] font-semibold uppercase tracking-[0.2em] ${m.tone === "brand" ? "text-brand-400" : "text-info"}`}>{m.tag}</span>
              <h3 className="mt-3 font-[family-name:var(--font-display)] text-3xl font-semibold uppercase leading-tight tracking-wide">{m.title}</h3>
              <p className="mt-3 max-w-md text-sm leading-relaxed text-muted">{m.body}</p>
              <code className="mt-6 inline-block rounded-[var(--radius-sm)] border border-border-strong bg-bg/60 px-3 py-2 font-[family-name:var(--font-mono)] text-sm">{m.formula}</code>
            </div>
          ))}
        </div>
        <p className="mt-8 max-w-3xl text-sm leading-relaxed text-muted">
          Small samples are shrunk toward the competition average (Bayesian smoothing), recent matches carry more weight, and every estimate is
          labelled with its confidence and data quality. Model outputs are shown as uncalibrated until enough out-of-sample evidence exists.
        </p>
      </section>

      {/* PLATFORM BENTO */}
      <section id="features" className="scroll-mt-20 border-y border-border bg-surface/30">
        <div className="mx-auto max-w-7xl px-4 py-24 sm:px-6">
          <Eyebrow>The platform</Eyebrow>
          <H2 className="max-w-3xl">Everything you need between the scan and the slip</H2>
          <div className="mt-12 grid gap-4 lg:grid-cols-12">
            <div className="panel rounded-[var(--radius-xl)] p-7 lg:col-span-7">
              <Radar className="h-5 w-5 text-brand-400" aria-hidden />
              <h3 className="mt-4 font-[family-name:var(--font-display)] text-2xl font-semibold uppercase tracking-wide">Global match scanner</h3>
              <p className="mt-2 max-w-lg text-sm text-muted">One card per game with both picks side by side. Filter by date, country, competition, gender, probability, sample size and data quality.</p>
              <div className="mt-6 grid grid-cols-2 gap-3 sm:max-w-md">
                {[["No goal 0-5'", "92.3%", "border-brand-500/50 bg-brand-500/10"], ["Level at 5'", "92.4%", "border-border-strong bg-bg/50"]].map(([l, v, c]) => (
                  <div key={l} className={`rounded-[var(--radius-md)] border p-3 ${c}`}><p className="font-[family-name:var(--font-mono)] text-[10px] uppercase tracking-wider text-muted">{l}</p><p className="numeral mt-1 text-3xl leading-none">{v}</p></div>
                ))}
              </div>
            </div>
            <div className="panel rounded-[var(--radius-xl)] p-7 lg:col-span-5">
              <Gauge className="h-5 w-5 text-brand-400" aria-hidden />
              <h3 className="mt-4 font-[family-name:var(--font-display)] text-2xl font-semibold uppercase tracking-wide">An honest track record</h3>
              <p className="mt-2 text-sm text-muted">Every prediction is stored before kick-off and can never be edited. Brier score, log loss and calibration are visible to users, misses included.</p>
              <div className="mt-6 flex items-center gap-2 text-[11px] text-subtle"><span className="rounded-[4px] bg-brand-500/15 px-1.5 py-0.5 font-[family-name:var(--font-mono)] text-brand-300">T-3h stored</span><span className="h-px flex-1 bg-border-strong" /><span className="rounded-[4px] bg-surface-3 px-1.5 py-0.5 font-[family-name:var(--font-mono)]">kick-off</span><span className="h-px flex-1 bg-border-strong" /><span className="rounded-[4px] bg-surface-3 px-1.5 py-0.5 font-[family-name:var(--font-mono)]">settled</span></div>
            </div>
            <div className="panel rounded-[var(--radius-xl)] p-7 lg:col-span-4">
              <BarChart3 className="h-5 w-5 text-brand-400" aria-hidden />
              <h3 className="mt-4 font-[family-name:var(--font-display)] text-xl font-semibold uppercase tracking-wide">Match intelligence</h3>
              <p className="mt-2 text-sm text-muted">Last 5/10/20 form, home and away splits, head-to-head, competition baselines and first-goal timing.</p>
            </div>
            <div className="panel rounded-[var(--radius-xl)] p-7 lg:col-span-4">
              <Database className="h-5 w-5 text-brand-400" aria-hidden />
              <h3 className="mt-4 font-[family-name:var(--font-display)] text-xl font-semibold uppercase tracking-wide">Data you can audit</h3>
              <p className="mt-2 text-sm text-muted">Raw provider payloads, event-timeline reconciliation and a visible reliability score on every match.</p>
            </div>
            <div className="panel relative overflow-hidden rounded-[var(--radius-xl)] border-brand-500/30 p-7 lg:col-span-4">
              <span className="absolute inset-0 bg-gradient-to-br from-brand-500/10 to-transparent" aria-hidden />
              <div className="relative">
                <Ticket className="h-5 w-5 text-brand-400" aria-hidden />
                <h3 className="mt-4 font-[family-name:var(--font-display)] text-xl font-semibold uppercase tracking-wide">Ticket &amp; booking code</h3>
                <p className="mt-2 text-sm text-muted">Tap the picks you trust, choose your bookmaker and get a booking code for the same ticket, where that bookmaker is connected. You place it yourself.</p>
              </div>
            </div>
            <div className="panel rounded-[var(--radius-xl)] p-7 lg:col-span-6">
              <Scale className="h-5 w-5 text-brand-400" aria-hidden />
              <h3 className="mt-4 font-[family-name:var(--font-display)] text-xl font-semibold uppercase tracking-wide">Odds comparison</h3>
              <p className="mt-2 text-sm text-muted">Where supported bookmakers price these markets, compare their odds with the model&apos;s fair odds and estimated edge.</p>
            </div>
            <div className="panel rounded-[var(--radius-xl)] p-7 lg:col-span-6">
              <Bell className="h-5 w-5 text-brand-400" aria-hidden />
              <h3 className="mt-4 font-[family-name:var(--font-display)] text-xl font-semibold uppercase tracking-wide">Alerts</h3>
              <p className="mt-2 text-sm text-muted">Get notified when a match newly qualifies under your plan&apos;s scanner, and when your saved games settle.</p>
            </div>
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section id="pricing" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-24 sm:px-6">
        <Eyebrow>Pricing</Eyebrow>
        <H2 className="mb-12 max-w-3xl">Start free. Upgrade when it earns its place.</H2>
        <PricingTable />
      </section>

      {/* FAQ */}
      <section id="faq" className="scroll-mt-20 border-t border-border bg-surface/30">
        <div className="mx-auto grid max-w-7xl gap-12 px-4 py-24 sm:px-6 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="lg:sticky lg:top-28 lg:self-start">
            <Eyebrow>Straight answers</Eyebrow>
            <H2>Questions, answered plainly</H2>
            <p className="mt-4 text-sm text-muted">Betting products attract hype. Here is exactly what First5Minute is, and is not.</p>
            <ButtonLink href="/register" className="mt-6">Create a free account</ButtonLink>
          </div>
          <div className="divide-y divide-border rounded-[var(--radius-xl)] border border-border bg-surface/70">
            {FAQ.map((f) => (
              <details key={f.q} className="group px-6 py-5">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                  {f.q}
                  <span className="numeral text-2xl text-brand-400 transition-transform group-open:rotate-45">+</span>
                </summary>
                <p className="mt-3 text-sm leading-relaxed text-muted">{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* CLOSING CTA */}
      <section className="bg-stadium pitch-lines relative overflow-hidden border-t border-border">
        <div className="mx-auto max-w-5xl px-4 py-24 text-center sm:px-6">
          <span className="ribbon mx-auto" aria-hidden />
          <h2 className="mt-6 font-[family-name:var(--font-display)] text-5xl font-bold uppercase leading-[1] tracking-wide sm:text-7xl">See today&apos;s opening-minute picture</h2>
          <p className="mt-4 text-muted">Create a free account. No card required.</p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <ButtonLink href="/register" size="lg">Create account</ButtonLink>
            <ButtonLink href="/login" size="lg" variant="outline">Sign in</ButtonLink>
          </div>
          <p className="mt-6 text-xs text-subtle">18+ only. <Link href="/pricing" className="underline">See plans</Link></p>
        </div>
      </section>
    </>
  );
}
