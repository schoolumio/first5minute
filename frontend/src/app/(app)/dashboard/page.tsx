"use client";

import Link from "next/link";
import { Activity, ArrowUpRight, Radar } from "lucide-react";
import { useMemo, useState } from "react";
import { TrendChart, type TrendPoint } from "@/components/charts/charts";
import { PageHeader } from "@/components/layout/app-shell";
import { OutcomeBadge } from "@/components/match/prediction-row";
import { PickChip } from "@/components/match/pick-chip";
import { Badge, DemoBadge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ProbabilityValue, Table, Tabs, Td, Th } from "@/components/ui/data";
import { Alert, EmptyState, Skeleton } from "@/components/ui/feedback";
import { useAuth } from "@/lib/auth";
import { kickoff, MARKET_LABEL, num, pct, relative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Market, Page, Prediction } from "@/lib/types";

interface Summary {
  fixtures_today: number; fixtures_analysed_today: number; upcoming_fixtures: number; lookahead_hours: number;
  qualified: number; watchlist: number; excluded: number; by_market: Record<string, Record<string, number>>;
}
interface ScannerRes { items: Prediction[]; total: number; locked_count: number; plan: string }
interface PerfBlock { sample_size: number; brier: number | null; log_loss: number | null; hit_rate: number | null; base_rate: number | null; mean_predicted: number | null; is_demo: boolean }
interface Perf { markets: Record<string, { all: PerfBlock; qualified: PerfBlock }>; disclaimer: string }

function RankedPicks() {
  const { user } = useAuth();
  const { data, loading, error } = useApi<ScannerRes>(user?.email_verified ? "/scanner" : null, {
    categories: ["qualified", "watchlist"], sort: "probability", page_size: 24,
  });
  const games = useMemo(() => {
    const by = new Map<number, { fixture: NonNullable<Prediction["fixture"]>; a?: Prediction; b?: Prediction; best: number }>();
    for (const p of data?.items ?? []) {
      if (!p.fixture) continue;
      const g = by.get(p.fixture_id) ?? { fixture: p.fixture, best: 0 };
      if (p.market === "MARKET_A") g.a = p; else g.b = p;
      g.best = Math.max(g.best, p.probability);
      by.set(p.fixture_id, g);
    }
    return [...by.values()].sort((x, y) => y.best - x.best).slice(0, 6);
  }, [data]);
  if (!user?.email_verified) return <CardBody><Alert tone="warn">Verify your email to see scanner predictions.</Alert></CardBody>;
  if (loading) return <CardBody className="space-y-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16" />)}</CardBody>;
  if (error) return <CardBody><Alert tone="danger">{error.message}</Alert></CardBody>;
  if (!games.length)
    return <EmptyState icon={Radar} title="No qualified or watchlist matches in the current window">The scanner re-runs automatically as new fixtures and data arrive.</EmptyState>;
  return (
    <>
      <ol className="divide-y divide-border/70">
        {games.map((g, i) => (
          <li key={g.fixture.id} className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-[auto_minmax(0,1fr)_auto_auto]">
            <span className="numeral text-2xl text-border-strong">{String(i + 1).padStart(2, "0")}</span>
            <div className="min-w-0">
              <Link href={`/matches/${g.fixture.id}`} className="group flex items-center gap-1 break-words font-semibold leading-snug hover:text-brand-400">
                {g.fixture.home_team.name} <span className="font-normal text-muted">vs</span> {g.fixture.away_team.name}
                <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-subtle group-hover:text-brand-400" aria-hidden />
              </Link>
              <p className="mt-0.5 truncate text-xs text-muted">{g.fixture.competition.name} · {kickoff(g.fixture.kickoff_at)} <span className="text-subtle">· {relative(g.fixture.kickoff_at)}</span>{g.a?.is_demo && " · demo"}</p>
            </div>
            <PickChip market="MARKET_A" p={g.a} className="col-span-1 col-start-2 sm:col-start-auto" />
            <PickChip market="MARKET_B" p={g.b} className="col-span-1 col-start-2 sm:col-start-auto" />
          </li>
        ))}
      </ol>
      {data && data.locked_count > 0 && (
        <p className="border-t border-border/70 px-5 py-3 text-xs text-muted">
          {data.locked_count} more matches are available on paid plans. <Link className="text-brand-400 hover:underline" href="/pricing">Upgrade</Link>
        </p>
      )}
    </>
  );
}

function Scoreboard({ s }: { s: Summary }) {
  const cells = [
    { label: "Fixtures today", value: s.fixtures_today, sub: `${s.fixtures_analysed_today} analysed`, tone: "text-fg" },
    { label: "Qualified", value: s.qualified, sub: `next ${s.lookahead_hours}h · both markets`, tone: "text-brand-400" },
    { label: "Watchlist", value: s.watchlist, sub: "lower confidence", tone: "text-info" },
    { label: "Upcoming", value: s.upcoming_fixtures, sub: `${s.excluded} excluded for data`, tone: "text-warn" },
  ];
  return (
    <section aria-label="Today at a glance" className="panel relative overflow-hidden rounded-[var(--radius-xl)]">
      <div className="pitch-lines absolute inset-0 opacity-60" aria-hidden />
      <div className="relative grid grid-cols-2 gap-y-6 px-5 py-6 sm:px-8 lg:grid-cols-[repeat(4,1fr)] lg:gap-0">
        {cells.map((c, i) => (
          <div key={c.label} className={`flex ${i > 0 ? "lg:border-l lg:border-border-strong/60 lg:pl-8" : ""} ${i === 2 ? "border-border-strong/60" : ""}`}>
            <div>
              <p className="font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">{c.label}</p>
              <p className={`numeral mt-2 text-[56px] leading-none sm:text-[64px] ${c.tone}`}>{c.value}</p>
              <p className="mt-2 text-xs text-subtle">{c.sub}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function TrendCard() {
  const [market, setMarket] = useState<Market>("MARKET_A");
  const [table, setTable] = useState(false);
  const { data, loading } = useApi<{ points: TrendPoint[]; capped_by_plan: boolean; is_demo: boolean; days: number; note: string }>(
    "/predictions/performance/trend", { market, days: 90, bucket: "week" });
  return (
    <Card className="mt-6">
      <CardHeader
        title="Model performance over time"
        description={`Weekly observed hit rate vs mean estimate · last ${data?.days ?? 90} days`}
        action={<div className="flex items-center gap-2">{data?.is_demo && <DemoBadge />}<Tabs value={market} onChange={setMarket} options={[{ value: "MARKET_A", label: "Market A" }, { value: "MARKET_B", label: "Market B" }]} /></div>}
      />
      <CardBody>
        {loading ? <Skeleton className="h-64" /> : !data || data.points.length < 2 ? (
          <EmptyState icon={Activity} title="Not enough settled predictions for a trend yet">A trend needs at least two weeks with settled matches.</EmptyState>
        ) : (
          <>
            <TrendChart points={data.points} />
            <div className="mt-2 flex items-center justify-between text-xs text-subtle">
              <span>{data.note}</span>
              <button className="cursor-pointer text-brand-400 hover:underline" onClick={() => setTable(!table)}>{table ? "Hide" : "View as"} table</button>
            </div>
            {table && (
              <Table className="mt-3">
                <thead><tr><Th>Week of</Th><Th className="text-right">Settled</Th><Th className="text-right">Estimate</Th><Th className="text-right">Hit rate</Th><Th className="text-right">Brier</Th></tr></thead>
                <tbody>{data.points.map((p) => <tr key={p.period}><Td>{p.period}</Td><Td className="tabular text-right">{p.n}</Td><Td className="tabular text-right">{pct(p.mean_predicted)}</Td><Td className="tabular text-right">{pct(p.hit_rate)}</Td><Td className="tabular text-right">{num(p.brier)}</Td></tr>)}</tbody>
              </Table>
            )}
            {data.capped_by_plan && <p className="mt-3 text-xs text-muted">Free plan shows 30 days. <Link href="/pricing" className="text-brand-400 hover:underline">Upgrade</Link> for up to two years of history.</p>}
          </>
        )}
      </CardBody>
    </Card>
  );
}

export default function DashboardPage() {
  const { user, status } = useAuth();
  const summary = useApi<Summary>("/scanner/summary");
  const recent = useApi<Page<Prediction>>("/predictions", { page_size: 8, category: "qualified" });
  const perf = useApi<Perf>("/predictions/performance");

  const s = summary.data;
  const perfA = perf.data?.markets.MARKET_A;
  const perfB = perf.data?.markets.MARKET_B;
  const anyDemo = perfA?.all.is_demo || perfB?.all.is_demo;

  return (
    <>
      <PageHeader
        eyebrow="Match-day briefing"
        title={`Good to see you${user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}`}
        description="The opening-minute picture across every monitored competition: where the model sees the strongest first-five-minute edges, and how it has been doing."
        action={<ButtonLink href="/scanner" size="md"><Radar className="h-4 w-4" /> Open scanner</ButtonLink>}
      />

      {summary.loading || !s ? <Skeleton className="h-40 rounded-[var(--radius-xl)]" /> : <Scoreboard s={s} />}

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card>
          <CardHeader title="Strongest picks, next 72 hours" description="Both markets per game, ranked by the model's highest estimate. Tap a pick to add it to your ticket." action={<Link href="/scanner" className="text-xs font-semibold text-brand-400 hover:underline">All games →</Link>} />
          <RankedPicks />
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Track record" description="Settled qualified predictions" action={anyDemo ? <DemoBadge /> : null} />
            <CardBody className="space-y-5">
              {perf.loading ? <Skeleton className="h-32" /> : (
                (["MARKET_A", "MARKET_B"] as Market[]).map((m) => {
                  const q = perf.data?.markets[m]?.qualified;
                  return (
                    <div key={m}>
                      <p className="font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">{MARKET_LABEL[m]}</p>
                      {q && q.sample_size > 0 ? (
                        <div className="mt-1 flex items-end justify-between gap-3">
                          <p className="numeral text-[44px] leading-none text-brand-400">{pct(q.hit_rate)}</p>
                          <dl className="grid grid-cols-2 gap-x-5 text-right text-xs">
                            <div><dt className="text-subtle">Brier</dt><dd className="tabular font-semibold">{num(q.brier)}</dd></div>
                            <div><dt className="text-subtle">Settled</dt><dd className="tabular font-semibold">{q.sample_size}</dd></div>
                          </dl>
                        </div>
                      ) : <p className="mt-1 text-sm text-muted">No settled qualified predictions yet.</p>}
                    </div>
                  );
                })
              )}
              <p className="text-[11px] leading-relaxed text-subtle">{perf.data?.disclaimer}</p>
              <ButtonLink href="/predictions" variant="outline" size="sm" className="w-full">Full track record</ButtonLink>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Pipeline status" />
            <CardBody className="space-y-3 text-sm">
              <p className="flex items-center justify-between"><span className="text-muted">Data source</span>
                <Badge tone={status?.data_mode === "live" ? "brand" : "demo"}>{status?.data_mode === "live" ? status.football_provider : "Demo data"}</Badge></p>
              {(["sync_fixtures", "scanner", "settlement"] as const).map((job) => {
                const run = status?.last_runs?.[job];
                return (
                  <p key={job} className="flex items-center justify-between gap-2">
                    <span className="text-muted">{{ sync_fixtures: "Fixture sync", scanner: "Scanner", settlement: "Settlement" }[job]}</span>
                    <span className="flex items-center gap-1.5 text-xs">{run ? <><Badge tone={run.status === "success" ? "brand" : run.status === "failed" ? "danger" : "warn"}>{run.status}</Badge><span className="text-subtle">{relative(run.at)}</span></> : <span className="text-subtle">never</span>}</span>
                  </p>
                );
              })}
              <p className="flex items-center justify-between gap-2"><span className="text-muted">Odds ({status?.odds_provider === "none" ? "off" : status?.odds_provider})</span>
                <span className="flex items-center gap-1.5 text-xs">{status?.last_runs?.odds_sync ? <><Badge tone={status.last_runs.odds_sync.status === "success" ? "brand" : "warn"}>{status.last_runs.odds_sync.status}</Badge><span className="text-subtle">{relative(status.last_runs.odds_sync.at)}</span></> : <span className="text-subtle">never</span>}</span></p>
            </CardBody>
          </Card>
        </div>
      </div>

      <TrendCard />

      <Card className="mt-6">
        <CardHeader title="Recent qualified predictions" description="Settled at the five-minute cutoff" action={<Link href="/predictions" className="text-xs text-brand-400 hover:underline">View all</Link>} />
        {recent.loading ? <CardBody><Skeleton className="h-40" /></CardBody> : !recent.data?.items.length ? (
          <EmptyState title="No qualified predictions yet">Predictions appear here once the scanner qualifies matches.</EmptyState>
        ) : (
          <Table>
            <thead><tr><Th>Fixture</Th><Th>Market</Th><Th className="text-right">Estimate</Th><Th>Score at 5&apos;</Th><Th>Result</Th></tr></thead>
            <tbody>
              {recent.data.items.map((p) => (
                <tr key={p.id} className="hover:bg-surface-2/50">
                  <Td>
                    <Link href={`/matches/${p.fixture_id}`} className="font-medium hover:text-brand-400">{p.fixture?.home_team.name} vs {p.fixture?.away_team.name}</Link>
                    <p className="text-xs text-subtle">{p.fixture && kickoff(p.fixture.kickoff_at)} {p.is_demo && "· demo"}</p>
                  </Td>
                  <Td className="text-muted">{MARKET_LABEL[p.market]}</Td>
                  <Td className="text-right"><ProbabilityValue value={p.probability} /></Td>
                  <Td className="tabular">{p.outcome?.home_score_at_cutoff != null ? `${p.outcome.home_score_at_cutoff}-${p.outcome.away_score_at_cutoff}` : "-"}</Td>
                  <Td><OutcomeBadge p={p} /></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
