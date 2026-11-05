"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ArrowLeft, Bookmark, Info } from "lucide-react";
import { ComparisonChart, SERIES, TimingChart } from "@/components/charts/charts";
import { OddsPanel } from "@/components/match/odds-panel";
import { OutcomeBadge } from "@/components/match/prediction-row";
import { AddToTicketButton } from "@/components/ticket/add-button";
import { Badge, CategoryBadge, DemoBadge, QualityIndicator } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ProbabilityBar, ProbabilityValue, Table, Tabs, Td, Th } from "@/components/ui/data";
import { Alert, EmptyState, Skeleton, UpgradeNotice } from "@/components/ui/feedback";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { MARKET_LABEL, MARKET_LONG, num, pct, relative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Fixture, Market, Prediction, TeamProfile, Window } from "@/lib/types";

interface Analysis {
  fixture: Fixture;
  locked: { extended_history: boolean; head_to_head: boolean; odds: boolean };
  home: TeamProfile; away: TeamProfile;
  head_to_head: { fixture_id: number; kickoff_at: string; home: string; away: string; score: [number, number]; score_at_cutoff: [number, number] | null }[];
  competition: Fixture["competition"] & { baseline_home_rate: number; baseline_away_rate: number; baseline_sample: number; clean_window_pct: number | null };
  predictions: Partial<Record<Market, Prediction>>;
  prediction_history: Prediction[];
}
function PredictionPanel({ p, market, fixture }: { p?: Prediction; market: Market; fixture: Fixture }) {
  if (!p) return <div className="rounded-[var(--radius-lg)] border border-border bg-surface p-5"><p className="text-sm text-muted">No {MARKET_LABEL[market]} prediction yet.</p></div>;
  const levels = (p.components.level_scores ?? null) as Record<string, number> | null;
  return (
    <div className="panel rounded-[var(--radius-lg)] p-6">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">{MARKET_LABEL[market]}</p>
          <p className="mt-0.5 text-xs text-subtle">{MARKET_LONG[market]}</p>
        </div>
        <CategoryBadge category={p.category} />
      </div>
      <p className="numeral mt-4 text-[72px] leading-none text-brand-400">{pct(p.probability)}</p>
      <ProbabilityBar value={p.probability} className="mt-3" />
      {p.is_current && <div className="mt-3"><AddToTicketButton p={{ ...p, fixture }} /></div>}
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted">Model confidence</dt><dd className="text-right font-semibold capitalize">{p.confidence} <span className="text-xs font-normal text-subtle">(±{pct(Number(p.components.uncertainty_sd ?? 0))})</span></dd>
        <dt className="text-muted">Data quality</dt><dd className="flex justify-end"><QualityIndicator quality={p.data_quality} /></dd>
        <dt className="text-muted">Sample (home / away)</dt><dd className="tabular text-right">{p.sample_home} / {p.sample_away}</dd>
        <dt className="text-muted">Expected early goals</dt><dd className="tabular text-right">{num(p.lambda_home)} / {num(p.lambda_away)}</dd>
        <dt className="text-muted">Model</dt><dd className="text-right text-xs">{p.model.name} v{p.model.version} <Badge className="ml-1">{p.model.calibration_status}</Badge></dd>
        <dt className="text-muted">Predicted</dt><dd className="text-right text-xs">{new Date(p.predicted_at).toLocaleString()}</dd>
      </dl>
      {typeof p.components.baseline_probability === "number" && p.components.model_variant !== "poisson_baseline" && (
        <p className="mt-3 rounded-[var(--radius-md)] border border-border bg-surface-2 px-3 py-2 text-xs text-muted">
          Estimate from <span className="font-semibold text-fg">{String(p.components.model_variant).replace("_", " ")}</span>. The plain Poisson baseline gives{" "}
          <span className="tabular font-semibold text-fg">{pct(p.components.baseline_probability as number)}</span>; the components below describe the baseline.
        </p>
      )}
      {levels && (
        <div className="mt-4 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3 text-xs">
          <p className="mb-1.5 font-semibold text-muted">Level-score components</p>
          <div className="grid grid-cols-4 gap-2 text-center">
            {Object.entries(levels).map(([k, v]) => (
              <div key={k}><p className="tabular font-semibold">{pct(v, 2)}</p><p className="text-subtle">{k === "other_level" ? "3-3+" : k}</p></div>
            ))}
          </div>
        </div>
      )}
      {p.category_reasons.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-muted">{p.category_reasons.map((r) => <li key={r} className="flex gap-1.5"><Info className="mt-0.5 h-3 w-3 shrink-0" />{r}</li>)}</ul>
      )}
      {p.outcome && <div className="mt-3 flex items-center justify-between text-sm"><span className="text-muted">Outcome at 5&apos;: {p.outcome.home_score_at_cutoff ?? "?"}-{p.outcome.away_score_at_cutoff ?? "?"}</span><OutcomeBadge p={p} /></div>}
    </div>
  );
}

function FormTable({ profile, color }: { profile: TeamProfile; color: string }) {
  return (
    <div>
      <p className="mb-2 flex items-center gap-2 text-sm font-semibold"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />{profile.team.name}</p>
      <Table>
        <thead><tr><Th>Date</Th><Th>Opponent</Th><Th className="text-center">FT</Th><Th className="text-center">At 5&apos;</Th><Th className="text-center">1st goal</Th></tr></thead>
        <tbody>
          {profile.recent_matches.map((m) => (
            <tr key={m.fixture_id}>
              <Td className="whitespace-nowrap text-xs text-muted">{new Date(m.kickoff_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</Td>
              <Td className="text-xs">{m.is_home ? "vs" : "@"} {m.opponent}</Td>
              <Td className="tabular text-center text-xs">{m.goals_for}-{m.goals_against}</Td>
              <Td className={cn("tabular text-center text-xs font-semibold", m.early_for == null ? "text-subtle" : m.early_for + (m.early_against ?? 0) === 0 ? "text-brand-400" : "text-warn")}>
                {m.reliable ? `${m.early_for}-${m.early_against}` : "n/a"}
              </Td>
              <Td className="tabular text-center text-xs text-muted">{m.first_goal_minute ? `${m.first_goal_minute}'` : m.reliable ? "-" : "n/a"}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {!profile.recent_matches.length && <p className="py-4 text-center text-sm text-muted">No historical matches recorded.</p>}
    </div>
  );
}

function Crest({ name, className = "" }: { name: string; className?: string }) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("");
  const hue = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  return (
    <span aria-hidden className={`numeral flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 text-xl text-white sm:h-16 sm:w-16 ${className}`}
      style={{ borderColor: `hsl(${hue} 60% 45%)`, background: `radial-gradient(circle at 30% 25%, hsl(${hue} 55% 32%), hsl(${hue} 45% 14%))` }}>{initials}</span>
  );
}

function WindowRow({ label, w }: { label: string; w?: Window }) {
  if (!w) return null;
  return (
    <tr>
      <Td className="text-xs text-muted">{label}</Td>
      <Td className="tabular text-center text-xs">{w.reliable_matches}/{w.matches}</Td>
      <Td className="tabular text-center text-xs">{pct(w.scored_early_pct, 0)}</Td>
      <Td className="tabular text-center text-xs">{pct(w.conceded_early_pct, 0)}</Td>
      <Td className="tabular text-center text-xs font-semibold">{pct(w.clean_window_pct, 0)}</Td>
      <Td className="tabular text-center text-xs">{pct(w.level_at_cutoff_pct, 0)}</Td>
    </tr>
  );
}

export default function MatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, loading, error } = useApi<Analysis>(`/fixtures/${id}/analysis`);
  const { has } = useAuth();
  const [win, setWin] = useState<"last5" | "last10" | "last20">("last10");
  const [saved, setSaved] = useState(false);

  // Deep link from the Odds page (#odds): the card only exists once data has loaded.
  useEffect(() => {
    if (data && typeof window !== "undefined" && window.location.hash === "#odds") {
      document.getElementById("odds")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [data]);

  if (loading) return <div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-72" /></div>;
  if (error || !data) return <Alert tone="danger">{error?.message ?? "Match not found"}</Alert>;
  const { fixture: fx, home, away } = data;
  const w = (p: TeamProfile) => p.windows[win] ?? p.windows.last5;

  return (
    <>
      <Link href="/scanner" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-fg"><ArrowLeft className="h-4 w-4" /> Back to scanner</Link>

      <section className="bg-stadium pitch-lines panel relative mb-6 overflow-hidden rounded-[var(--radius-xl)] px-5 py-7 sm:px-10 sm:py-9">
        <p className="flex flex-wrap items-center gap-2 font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">
          {fx.competition.name} {fx.round && <span>· {fx.round}</span>} {fx.is_demo && <DemoBadge />}
          {fx.competition.gender === "women" && <Badge tone="info">Women</Badge>}
          <span className="ml-auto capitalize text-subtle">{fx.status}</span>
        </p>
        <div className="mt-6 grid items-center gap-5 sm:grid-cols-[1fr_auto_1fr]">
          <div className="flex items-center gap-4 sm:justify-end sm:text-right">
            <h1 className="order-2 break-words font-[family-name:var(--font-display)] text-3xl font-semibold uppercase leading-none tracking-wide sm:order-1 sm:text-5xl">{home.team.name}</h1>
            <Crest name={home.team.name} className="order-1 sm:order-2" />
          </div>
          <div className="text-center">
            <p className="numeral text-xs uppercase tracking-[0.3em] text-subtle">vs</p>
            <p className="numeral mt-1 text-2xl">{new Date(fx.kickoff_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</p>
            <p className="text-[11px] text-subtle">{new Date(fx.kickoff_at).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })} · {relative(fx.kickoff_at)}</p>
            {fx.score.home != null && <p className="numeral mt-1 text-lg text-brand-300">FT {fx.score.home}-{fx.score.away}</p>}
          </div>
          <div className="flex items-center gap-4">
            <Crest name={away.team.name} />
            <h1 className="break-words font-[family-name:var(--font-display)] text-3xl font-semibold uppercase leading-none tracking-wide sm:text-5xl">{away.team.name}</h1>
          </div>
        </div>
        <div className="mt-7 flex flex-wrap items-center justify-between gap-3 border-t border-border/70 pt-4">
          <p className="text-xs text-muted">{fx.venue ? `${fx.venue} · ` : ""}the five-minute window opens at kick-off</p>
          <div className="flex items-center gap-2">
            {["finished", "abandoned"].includes(fx.status) && (
              <Badge tone={fx.timeline_status === "complete" ? "brand" : "warn"} title="Event-timeline reconciliation status">Timeline: {fx.timeline_status}</Badge>
            )}
            <Button variant="outline" size="sm" disabled={saved} onClick={async () => { await api("/saved-matches", { method: "POST", body: { fixture_id: fx.id } }); setSaved(true); }}>
              <Bookmark className="h-4 w-4" /> {saved ? "Saved" : "Save"}
            </Button>
          </div>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <PredictionPanel p={data.predictions.MARKET_A} market="MARKET_A" fixture={data.fixture} />
        <PredictionPanel p={data.predictions.MARKET_B} market="MARKET_B" fixture={data.fixture} />
      </div>

      <Card className="mt-6 scroll-mt-20" id="odds">
            <CardHeader title="Odds comparison" description="Only odds recorded from configured providers are shown" />
            <CardBody>{has("odds_comparison") ? <OddsPanel fixtureId={fx.id} /> : <UpgradeNotice feature="Odds comparison" />}</CardBody>
          </Card>

      <Card className="mt-6">
        <CardHeader title="Opening-minute profile" description="Share of each team's matches - goals measured at the five-minute cutoff"
          action={<Tabs value={win} onChange={setWin} options={[{ value: "last5", label: "Last 5" }, { value: "last10", label: "Last 10" }, { value: "last20", label: "Last 20" }]} />} />
        <CardBody>
          {data.locked.extended_history && win !== "last5" ? <UpgradeNotice plan="starter" feature="Last 10 and last 20 match analysis" /> : (
            <div className="grid gap-6 lg:grid-cols-2">
              <ComparisonChart homeName={home.team.name} awayName={away.team.name} rows={[
                { metric: "Scored early", home: w(home).scored_early_pct, away: w(away).scored_early_pct },
                { metric: "Conceded early", home: w(home).conceded_early_pct, away: w(away).conceded_early_pct },
                { metric: "0-0 at 5'", home: w(home).clean_window_pct, away: w(away).clean_window_pct },
                { metric: "Level at 5'", home: w(home).level_at_cutoff_pct, away: w(away).level_at_cutoff_pct },
              ]} />
              <Table>
                <thead><tr><Th>Split</Th><Th className="text-center">Reliable</Th><Th className="text-center">Scored</Th><Th className="text-center">Conceded</Th><Th className="text-center">0-0 at 5&apos;</Th><Th className="text-center">Level</Th></tr></thead>
                <tbody>
                  <WindowRow label={`${home.team.name} (all)`} w={w(home)} />
                  {home.venue && <WindowRow label={`${home.team.name} (home, last 10)`} w={home.venue} />}
                  <WindowRow label={`${away.team.name} (all)`} w={w(away)} />
                  {away.venue && <WindowRow label={`${away.team.name} (away, last 10)`} w={away.venue} />}
                </tbody>
              </Table>
            </div>
          )}
        </CardBody>
      </Card>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="First-goal timing" description="When the first goal arrived in each team's last 20 matches" />
          <CardBody>
            {home.first_goal_timing && away.first_goal_timing ? (
              <TimingChart home={home.first_goal_timing} away={away.first_goal_timing} homeName={home.team.name} awayName={away.team.name} />
            ) : <UpgradeNotice plan="starter" feature="First-goal timing distribution" />}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Competition baseline" description={data.competition.name} />
          <CardBody className="space-y-3 text-sm">
            <p className="flex justify-between"><span className="text-muted">Home early goals / match</span><span className="tabular font-semibold">{num(data.competition.baseline_home_rate)}</span></p>
            <p className="flex justify-between"><span className="text-muted">Away early goals / match</span><span className="tabular font-semibold">{num(data.competition.baseline_away_rate)}</span></p>
            <p className="flex justify-between"><span className="text-muted">0-0 at 5&apos; (competition)</span><span className="tabular font-semibold">{pct(data.competition.clean_window_pct)}</span></p>
            <p className="flex justify-between"><span className="text-muted">Matches in baseline</span><span className="tabular font-semibold">{data.competition.baseline_sample}</span></p>
            <p className="flex justify-between"><span className="text-muted">Quality tier</span><span className="capitalize">{data.competition.data_quality_tier}</span></p>
            <p className="text-xs text-subtle">Small competition samples are blended toward a global prior.</p>
          </CardBody>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Recent matches" description="Score at the five-minute cutoff highlighted" />
          <CardBody className="space-y-6">
            <FormTable profile={home} color={SERIES.home} />
            <FormTable profile={away} color={SERIES.away} />
          </CardBody>
        </Card>
        <div className="space-y-6">
          <Card>
            <CardHeader title="Head-to-head" />
            <CardBody>
              {data.locked.head_to_head ? <UpgradeNotice plan="starter" feature="Head-to-head analysis" /> : data.head_to_head.length ? (
                <Table>
                  <thead><tr><Th>Date</Th><Th>Fixture</Th><Th className="text-center">FT</Th><Th className="text-center">At 5&apos;</Th></tr></thead>
                  <tbody>{data.head_to_head.map((h) => (
                    <tr key={h.fixture_id}><Td className="text-xs text-muted">{new Date(h.kickoff_at).toLocaleDateString()}</Td><Td className="text-xs">{h.home} vs {h.away}</Td>
                      <Td className="tabular text-center text-xs">{h.score.join("-")}</Td><Td className="tabular text-center text-xs">{h.score_at_cutoff ? h.score_at_cutoff.join("-") : "n/a"}</Td></tr>
                  ))}</tbody>
                </Table>
              ) : <p className="text-sm text-muted">No previous meetings recorded.</p>}
            </CardBody>
          </Card>
          {data.prediction_history.length > 2 && (
            <Card>
              <CardHeader title="Prediction history for this fixture" description="Earlier estimates are superseded, never overwritten" />
              <Table>
                <thead><tr><Th>Predicted</Th><Th>Market</Th><Th className="text-right">Estimate</Th><Th>Status</Th></tr></thead>
                <tbody>{data.prediction_history.map((p) => (
                  <tr key={p.id}><Td className="text-xs text-muted">{new Date(p.predicted_at).toLocaleString()}</Td><Td className="text-xs">{MARKET_LABEL[p.market]}</Td>
                    <Td className="text-right"><ProbabilityValue value={p.probability} className="text-xs" /></Td><Td>{p.is_current ? <Badge tone="brand">current</Badge> : <Badge>superseded</Badge>}</Td></tr>
                ))}</tbody>
              </Table>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
