"use client";

import Link from "next/link";
import { Activity, CalendarDays, CheckCircle2, Eye, Radar, RefreshCw } from "lucide-react";
import { useState } from "react";
import { TrendChart, type TrendPoint } from "@/components/charts/charts";
import { PageHeader } from "@/components/layout/app-shell";
import { OutcomeBadge, PredictionCard } from "@/components/match/prediction-row";
import { Badge, DemoBadge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ProbabilityValue, Stat, Table, Tabs, Td, Th } from "@/components/ui/data";
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

function MarketPanel({ market }: { market: Market }) {
  const { user } = useAuth();
  const { data, loading, error } = useApi<ScannerRes>(user?.email_verified ? "/scanner" : null, {
    market, categories: ["qualified", "watchlist"], sort: "probability", page_size: 4,
  });
  if (!user?.email_verified) return <Alert tone="warn">Verify your email to see scanner predictions.</Alert>;
  if (loading) return <div className="grid gap-3 md:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-44" />)}</div>;
  if (error) return <Alert tone="danger">{error.message}</Alert>;
  if (!data?.items.length)
    return <EmptyState icon={Radar} title="No qualified or watchlist matches in the current window">The scanner re-runs automatically as new fixtures and data arrive.</EmptyState>;
  return (
    <>
      <div className="grid gap-3 md:grid-cols-2">{data.items.map((p) => <PredictionCard key={p.id} p={p} />)}</div>
      {data.locked_count > 0 && (
        <p className="mt-3 text-xs text-muted">
          {data.locked_count} more matches are available on paid plans. <Link className="text-brand-400 hover:underline" href="/pricing">Upgrade</Link>
        </p>
      )}
    </>
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
  const [market, setMarket] = useState<Market>("MARKET_A");
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
        title={`Good to see you${user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}`}
        description="Today's opening-minute picture across all monitored competitions."
        action={<ButtonLink href="/scanner" size="sm"><Radar className="h-4 w-4" /> Open scanner</ButtonLink>}
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {summary.loading || !s ? [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />) : (
          <>
            <Stat label="Fixtures today" value={s.fixtures_today} sub={`${s.fixtures_analysed_today} analysed by the models`} icon={CalendarDays} />
            <Stat label="Qualified" value={s.qualified} sub={`Next ${s.lookahead_hours}h · both markets`} icon={CheckCircle2} tone="brand" />
            <Stat label="Watchlist" value={s.watchlist} sub="Interesting, lower confidence" icon={Eye} tone="info" />
            <Stat label="Upcoming fixtures" value={s.upcoming_fixtures} sub={`${s.excluded} excluded for data quality`} icon={Activity} tone="warn" />
          </>
        )}
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title="Top upcoming matches"
            description="Highest model estimates in the scanner window"
            action={<Tabs value={market} onChange={setMarket} options={[{ value: "MARKET_A", label: MARKET_LABEL.MARKET_A }, { value: "MARKET_B", label: MARKET_LABEL.MARKET_B }]} />}
          />
          <CardBody><MarketPanel key={market} market={market} /></CardBody>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Model performance" description="Settled qualified predictions" action={anyDemo ? <DemoBadge /> : null} />
            <CardBody className="space-y-4">
              {perf.loading ? <Skeleton className="h-32" /> : (
                (["MARKET_A", "MARKET_B"] as Market[]).map((m) => {
                  const q = perf.data?.markets[m]?.qualified;
                  return (
                    <div key={m} className="rounded-[var(--radius-md)] border border-border bg-surface-2 p-3">
                      <p className="text-xs font-semibold text-muted">{MARKET_LABEL[m]}</p>
                      {q && q.sample_size > 0 ? (
                        <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                          <div><p className="tabular text-lg font-bold">{pct(q.hit_rate)}</p><p className="text-[11px] text-subtle">Hit rate</p></div>
                          <div><p className="tabular text-lg font-bold">{num(q.brier)}</p><p className="text-[11px] text-subtle">Brier</p></div>
                          <div><p className="tabular text-lg font-bold">{q.sample_size}</p><p className="text-[11px] text-subtle">Settled</p></div>
                        </div>
                      ) : <p className="mt-2 text-sm text-muted">No settled qualified predictions yet.</p>}
                    </div>
                  );
                })
              )}
              <p className="text-[11px] leading-relaxed text-subtle">{perf.data?.disclaimer}</p>
              <ButtonLink href="/predictions" variant="outline" size="sm" className="w-full">Full performance report</ButtonLink>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Data synchronisation" action={<RefreshCw className="h-4 w-4 text-muted" />} />
            <CardBody className="space-y-2.5 text-sm">
              <p className="flex items-center justify-between">
                <span className="text-muted">Data source</span>
                <Badge tone={status?.data_mode === "live" ? "brand" : "demo"}>{status?.data_mode === "live" ? status.football_provider : "Demo data"}</Badge>
              </p>
              {(["sync_fixtures", "scanner", "settlement"] as const).map((job) => {
                const run = status?.last_runs?.[job];
                return (
                  <p key={job} className="flex items-center justify-between">
                    <span className="text-muted">{{ sync_fixtures: "Fixture sync", scanner: "Scanner", settlement: "Settlement" }[job]}</span>
                    <span className="text-xs">{run ? <><Badge tone={run.status === "success" ? "brand" : run.status === "failed" ? "danger" : "warn"}>{run.status}</Badge> <span className="ml-1 text-subtle">{relative(run.at)}</span></> : <span className="text-subtle">never</span>}</span>
                  </p>
                );
              })}
              <p className="flex items-center justify-between">
                <span className="text-muted">Odds ({status?.odds_provider === "none" ? "not configured" : status?.odds_provider})</span>
                <span className="text-xs">{status?.last_runs?.odds_sync ? <><Badge tone={status.last_runs.odds_sync.status === "success" ? "brand" : "warn"}>{status.last_runs.odds_sync.status}</Badge> <span className="ml-1 text-subtle">{relative(status.last_runs.odds_sync.at)}</span></> : <span className="text-subtle">never</span>}</span>
              </p>
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
