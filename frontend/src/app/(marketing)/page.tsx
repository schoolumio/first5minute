import {
  Activity,
  BarChart3,
  Bell,
  CalendarClock,
  Database,
  Filter,
  Gauge,
  Radar,
  ShieldCheck,
  Timer,
} from "lucide-react";
import { PricingTable } from "@/components/pricing-table";
import { ButtonLink } from "@/components/ui/button";

const STEPS = [
  { icon: CalendarClock, title: "Collect fixtures", body: "Upcoming fixtures across men's, women's, domestic, continental and international football are synchronised from licensed data providers." },
  { icon: Timer, title: "Rebuild every opening", body: "Goal events with timestamps reconstruct the score at the exact settlement cutoff - handling own goals, VAR cancellations and stoppage time." },
  { icon: Activity, title: "Model both markets", body: "Smoothed early-scoring and early-conceding rates feed two separate Poisson models, using only information available before kick-off." },
  { icon: Radar, title: "Rank and qualify", body: "Matches are ranked by estimated probability, sample size and data quality - then marked Qualified, Watchlist or Excluded." },
];

const FEATURES = [
  { icon: Radar, title: "Global match scanner", body: "Filter by date, country, competition, gender, market, probability, sample size and data quality." },
  { icon: BarChart3, title: "Match intelligence", body: "Last 5/10/20 form, home/away splits, head-to-head, competition baselines and first-goal timing." },
  { icon: Database, title: "Data you can audit", body: "Raw provider payloads, event-timeline reconciliation and a visible reliability score on every match." },
  { icon: Gauge, title: "Honest performance", body: "Every prediction is stored before kick-off and can never be edited. Brier score, log loss and calibration are public to users." },
  { icon: Filter, title: "Odds comparison", body: "Where supported bookmakers price these markets, compare odds and open their pages via authorised links." },
  { icon: Bell, title: "Notifications", body: "Get alerted when a match newly qualifies under your plan's scanner." },
];

const FAQ = [
  { q: "Is this a guaranteed betting system?", a: "No. Project Five produces statistical estimates. Five-minute markets are low-scoring and noisy; even well-calibrated probabilities lose regularly. We never advertise guaranteed winnings or accuracy." },
  { q: "What exactly is the five-minute cutoff?", a: "By default the window is 00:00-04:59 of match time, measured from the actual kick-off. Bookmakers differ, so settlement rules are configurable, and goals whose timestamps are too imprecise to place relative to the cutoff are marked unresolved rather than guessed." },
  { q: "What is the difference between the two markets?", a: "Market A wins only if no goal is scored before the cutoff (0-0). Market B wins if the score is level at the cutoff, so 0-0, 1-1 and 2-2 all count. They are modelled and reported separately." },
  { q: "Why are some matches excluded?", a: "We never assign a qualifying prediction to a fixture without enough reliable, timestamped history. Competitions with poor event coverage are flagged and excluded rather than padded with assumptions." },
  { q: "Do you place bets or hold my money?", a: "No. Project Five never holds funds, never places bets and never asks for sportsbook passwords. You can open supported sportsbook pages and optionally record your own bets for tracking." },
  { q: "How do I pay?", a: "Paid plans are billed monthly in Naira through Paystack, which accepts Nigerian cards, bank transfers, USSD and international cards. You can cancel anytime." },
];

function SampleDashboard() {
  const rows = [
    { home: "Ashford Rovers", away: "Calder City", comp: "Demo Premier Division", p: 0.912, q: 3, cat: "Qualified" },
    { home: "Glenrock Union", away: "Oakfield Town", comp: "Demo Liga Norte", p: 0.903, q: 2, cat: "Qualified" },
    { home: "Kingsport Women", away: "Lakeside Women", comp: "Demo Women's Super League", p: 0.884, q: 2, cat: "Watchlist" },
  ];
  return (
    <div className="relative rounded-[var(--radius-xl)] border border-border bg-surface/80 p-4 shadow-2xl backdrop-blur sm:p-5">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted">Scanner · No goal 0-5&apos;</p>
        <span className="rounded-full border border-demo/40 bg-demo/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-demo">
          Illustrative · fictional teams
        </span>
      </div>
      <div className="space-y-2">
        {rows.map((r) => (
          <div key={r.home} className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-border bg-surface-2 px-3 py-2.5">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{r.home} <span className="text-muted">vs</span> {r.away}</p>
              <p className="truncate text-[11px] text-subtle">{r.comp}</p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="flex items-end gap-0.5">
                {[0, 1, 2].map((i) => <span key={i} className={`w-1 rounded-sm ${i < r.q ? "bg-brand-500" : "bg-border-strong"}`} style={{ height: 6 + i * 3 }} />)}
              </span>
              <span className={`text-[10px] font-semibold uppercase ${r.cat === "Qualified" ? "text-brand-400" : "text-info"}`}>{r.cat}</span>
              <span className="tabular w-14 text-right font-[family-name:var(--font-mono)] text-sm font-semibold">{(r.p * 100).toFixed(1)}%</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-7 items-end gap-1.5" aria-hidden>
        {[34, 22, 18, 26, 20, 16, 12].map((h, i) => (
          <div key={i} className={`rounded-t ${i === 0 ? "bg-brand-500" : "bg-surface-3"}`} style={{ height: h * 2 }} />
        ))}
      </div>
      <p className="mt-2 text-[11px] text-subtle">First-goal timing distribution (minutes 1-5 highlighted). Example values for illustration only.</p>
    </div>
  );
}

export default function LandingPage() {
  return (
    <>
      <section className="pitch-grid relative overflow-hidden border-b border-border">
        <div className="mx-auto grid max-w-7xl items-center gap-12 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:py-24">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full border border-brand-500/30 bg-brand-500/10 px-3 py-1 text-xs font-semibold text-brand-400">
              <ShieldCheck className="h-3.5 w-3.5" /> Global football intelligence
            </p>
            <h1 className="mt-5 font-[family-name:var(--font-display)] text-4xl font-extrabold leading-[1.08] tracking-tight sm:text-5xl lg:text-6xl">
              The first five minutes.<br /><span className="text-brand-500">Decoded.</span>
            </h1>
            <p className="mt-5 max-w-xl text-lg text-muted">
              Project Five analyses goal-event timelines across global football to estimate the probability of no goal - or a level
              score - at the five-minute cutoff. Transparent models, visible data quality, no hype.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <ButtonLink href="/register" size="lg">Start free</ButtonLink>
              <ButtonLink href="#how-it-works" size="lg" variant="outline">How the scanner works</ButtonLink>
            </div>
            <p className="mt-4 text-xs text-subtle">18+ only. Statistical estimates, not guarantees.</p>
          </div>
          <SampleDashboard />
        </div>
      </section>

      <section id="how-it-works" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-20 sm:px-6">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-400">How it works</p>
        <h2 className="mt-2 font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight">From raw fixtures to ranked matches</h2>
        <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <div key={s.title} className="rounded-[var(--radius-lg)] border border-border bg-surface p-5">
              <div className="flex items-center justify-between">
                <s.icon className="h-5 w-5 text-brand-500" />
                <span className="font-[family-name:var(--font-mono)] text-xs text-subtle">0{i + 1}</span>
              </div>
              <p className="mt-4 font-semibold">{s.title}</p>
              <p className="mt-1.5 text-sm text-muted">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="markets" className="scroll-mt-20 border-y border-border bg-surface/40">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-400">Two markets, two models</p>
          <h2 className="mt-2 font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight">Kept strictly separate</h2>
          <div className="mt-10 grid gap-4 lg:grid-cols-2">
            {[
              { tag: "Market A", title: "No goal in the first five minutes", body: "Wins only if the score is 0-0 at the cutoff. Expected early goals for each side combine attacking and defensive strengths with the competition baseline.", formula: "P(no goal) = e^-(λhome + λaway)" },
              { tag: "Market B", title: "Level at five minutes", body: "Wins if the scores are equal at the cutoff - 0-0, 1-1, 2-2 or any level score - computed from separate home and away early-goal distributions.", formula: "P(level) = Σk P(H=k)·P(A=k)" },
            ].map((m) => (
              <div key={m.tag} className="rounded-[var(--radius-xl)] border border-border bg-surface p-6">
                <span className="text-xs font-semibold uppercase tracking-wider text-brand-400">{m.tag}</span>
                <h3 className="mt-2 text-xl font-semibold">{m.title}</h3>
                <p className="mt-2 text-sm text-muted">{m.body}</p>
                <code className="mt-4 inline-block rounded-[var(--radius-sm)] border border-border bg-surface-2 px-3 py-1.5 font-[family-name:var(--font-mono)] text-sm text-fg">
                  {m.formula}
                </code>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-muted">
            Small samples are shrunk toward the competition average (Bayesian smoothing), recent matches carry more weight, and every
            estimate is labelled with its confidence and data quality. Model outputs are shown as uncalibrated until enough
            out-of-sample evidence exists.
          </p>
        </div>
      </section>

      <section id="features" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-20 sm:px-6">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-400">Features</p>
        <h2 className="mt-2 font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight">A trading-terminal view of the opening minutes</h2>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-[var(--radius-lg)] border border-border bg-surface p-5">
              <f.icon className="h-5 w-5 text-brand-500" />
              <p className="mt-3 font-semibold">{f.title}</p>
              <p className="mt-1.5 text-sm text-muted">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="pricing" className="scroll-mt-20 border-y border-border bg-surface/40">
        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-400">Pricing</p>
          <h2 className="mb-10 mt-2 font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight">Start free. Upgrade when it earns its place.</h2>
          <PricingTable />
        </div>
      </section>

      <section id="faq" className="mx-auto max-w-3xl scroll-mt-20 px-4 py-20 sm:px-6">
        <h2 className="font-[family-name:var(--font-display)] text-3xl font-bold tracking-tight">Frequently asked questions</h2>
        <div className="mt-8 divide-y divide-border rounded-[var(--radius-lg)] border border-border bg-surface">
          {FAQ.map((f) => (
            <details key={f.q} className="group px-5 py-4">
              <summary className="flex cursor-pointer list-none items-center justify-between font-medium">
                {f.q}
                <span className="ml-4 text-brand-400 transition-transform group-open:rotate-45">+</span>
              </summary>
              <p className="mt-2 text-sm text-muted">{f.a}</p>
            </details>
          ))}
        </div>
        <div className="mt-12 rounded-[var(--radius-xl)] border border-brand-500/30 bg-brand-500/5 p-8 text-center">
          <h3 className="font-[family-name:var(--font-display)] text-2xl font-bold">See today&apos;s opening-minute picture</h3>
          <p className="mt-2 text-sm text-muted">Create a free account - no card required.</p>
          <div className="mt-5 flex justify-center gap-3">
            <ButtonLink href="/register">Create account</ButtonLink>
            <ButtonLink href="/login" variant="outline">Sign in</ButtonLink>
          </div>
        </div>
      </section>
    </>
  );
}
