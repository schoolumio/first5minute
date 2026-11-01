"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { CalibrationChart } from "@/components/charts/charts";
import { PageHeader } from "@/components/layout/app-shell";
import { OutcomeBadge } from "@/components/match/prediction-row";
import { CategoryBadge, DemoBadge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Pager, ProbabilityValue, Stat, Table, Tabs, Td, Th } from "@/components/ui/data";
import { Alert, EmptyState, Skeleton, UpgradeNotice } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { useAuth } from "@/lib/auth";
import { kickoff, MARKET_LABEL, num, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Competition, Market, Page, Prediction } from "@/lib/types";

interface Block {
  sample_size: number; base_rate: number | null; mean_predicted: number | null; brier: number | null; log_loss: number | null;
  ece: number | null; hit_rate: number | null; precision: number | null; recall: number | null; void_or_unresolved: number;
  calibration?: { mean_predicted: number; observed_rate: number; count: number }[]; is_demo: boolean;
}
interface Perf {
  markets: Record<string, { all: Block; qualified: Block }>; detailed: boolean; disclaimer: string;
  models: { id: number; market: string; name: string; version: string; calibration_status: string }[];
  walk_forward?: { model_version_id: number; metric: string; value: number | null; sample_size: number; is_demo: boolean }[];
}

function Performance() {
  const [market, setMarket] = useState<Market>("MARKET_A");
  const { data, loading } = useApi<Perf>("/predictions/performance");
  if (loading || !data) return <Skeleton className="h-64" />;
  const m = data.markets[market];
  const model = data.models.find((x) => x.market === market);
  const wf = (data.walk_forward ?? []).filter((x) => x.model_version_id === model?.id);
  const wfMetric = (name: string) => wf.find((x) => x.metric === name);
  return (
    <Card>
      <CardHeader title="Model performance" description={model ? `${model.name} v${model.version} · ${model.calibration_status}` : undefined}
        action={<div className="flex items-center gap-2">{m.all.is_demo && <DemoBadge />}<Tabs value={market} onChange={setMarket} options={[{ value: "MARKET_A", label: "Market A" }, { value: "MARKET_B", label: "Market B" }]} /></div>} />
      <CardBody>
        {m.all.sample_size === 0 ? <EmptyState title="No settled predictions yet">Performance appears once predicted matches are played and settled.</EmptyState> : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Stat label="Settled" value={m.all.sample_size} sub={`${m.all.void_or_unresolved} void/unresolved`} />
              <Stat label="Qualified hit rate" value={pct(m.qualified.hit_rate)} sub={`${m.qualified.sample_size} qualified`} tone="brand" />
              <Stat label="Base rate" value={pct(m.all.base_rate)} sub={`Mean estimate ${pct(m.all.mean_predicted)}`} />
              <Stat label="Brier score" value={num(m.all.brier)} sub="Lower is better" />
              <Stat label="Log loss" value={num(m.all.log_loss)} sub="Lower is better" />
              <Stat label="Calibration error" value={num(m.all.ece)} sub="Expected (ECE)" />
            </div>
            <div className="mt-6 grid gap-6 lg:grid-cols-2">
              <div>
                <p className="mb-2 text-sm font-semibold">Calibration (reliability diagram)</p>
                {data.detailed && m.all.calibration ? <CalibrationChart bins={m.all.calibration} /> : <UpgradeNotice feature="Calibration analytics" />}
                <p className="mt-2 text-xs text-subtle">Dots on the dashed diagonal mean predicted probabilities matched observed frequencies.</p>
              </div>
              <div>
                <p className="mb-2 text-sm font-semibold">Walk-forward backtest</p>
                {!data.detailed ? <UpgradeNotice feature="Walk-forward validation" /> : wf.length ? (
                  <Table>
                    <thead><tr><Th>Metric</Th><Th className="text-right">Value</Th><Th className="text-right">Sample</Th></tr></thead>
                    <tbody>
                      {["brier", "log_loss", "ece", "base_rate", "mean_predicted", "precision", "recall"].map((k) => {
                        const v = wfMetric(k);
                        return v ? <tr key={k}><Td className="text-muted">{k.replace("_", " ")}</Td><Td className="tabular text-right">{num(v.value)}</Td><Td className="tabular text-right text-muted">{v.sample_size}</Td></tr> : null;
                      })}
                    </tbody>
                  </Table>
                ) : <p className="text-sm text-muted">No backtest has been run yet.</p>}
                {wf.some((x) => x.is_demo) && <Alert tone="demo" className="mt-3">Backtest computed on synthetic demo data - it says nothing about real-world accuracy.</Alert>}
                <p className="mt-3 text-xs text-subtle">ROI is only simulated with real bookmaker odds captured before kick-off. None is shown without them.</p>
              </div>
            </div>
          </>
        )}
        <p className="mt-6 text-xs text-subtle">{data.disclaimer}</p>
      </CardBody>
    </Card>
  );
}

export default function PredictionsPage() {
  const { has } = useAuth();
  const [page, setPage] = useState(1);
  const [f, setF] = useState({ market: "", competition_id: "", outcome: "", category: "", date_from: "", date_to: "" });
  const comps = useApi<Competition[]>("/competitions");
  const query = useMemo(() => ({ ...f, page, page_size: 20 }), [f, page]);
  const { data, loading, error } = useApi<Page<Prediction>>("/predictions", query);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setPage(1); setF({ ...f, [k]: e.target.value }); };

  return (
    <>
      <PageHeader title="Prediction history" description="Every prediction is stored before kick-off and can never be edited. Settled at the five-minute cutoff." />
      <Performance />

      <Card className="mt-6">
        <CardHeader title="All predictions" description={has("historical_analysis") ? undefined : "Free plan: last 7 days. Upgrade for full history."} />
        <CardBody className="grid grid-cols-2 gap-3 border-b border-border md:grid-cols-3 xl:grid-cols-6">
          <Field label="Market"><Select value={f.market} onChange={set("market")}><option value="">Both</option><option value="MARKET_A">Market A</option><option value="MARKET_B">Market B</option></Select></Field>
          <Field label="Competition"><Select value={f.competition_id} onChange={set("competition_id")}><option value="">All</option>{(comps.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
          <Field label="Outcome"><Select value={f.outcome} onChange={set("outcome")}><option value="">Any</option><option value="won">Correct</option><option value="lost">Incorrect</option><option value="void">Void</option><option value="unresolved">Unresolved</option><option value="pending">Pending</option></Select></Field>
          <Field label="Category"><Select value={f.category} onChange={set("category")}><option value="">Any</option><option value="qualified">Qualified</option><option value="watchlist">Watchlist</option><option value="below_threshold">Below threshold</option><option value="excluded">Excluded</option></Select></Field>
          <Field label="From"><Input type="date" value={f.date_from} onChange={set("date_from")} /></Field>
          <Field label="To"><Input type="date" value={f.date_to} onChange={set("date_to")} /></Field>
        </CardBody>
        {error && <CardBody><Alert tone="danger">{error.message}</Alert></CardBody>}
        {loading ? <CardBody><Skeleton className="h-64" /></CardBody> : !data?.items.length ? <EmptyState title="No predictions match these filters" /> : (
          <>
            <Table>
              <thead><tr><Th>Kick-off</Th><Th>Fixture</Th><Th>Market</Th><Th className="text-right">Estimate</Th><Th>Category</Th><Th>At 5&apos;</Th><Th>Outcome</Th><Th>Model</Th></tr></thead>
              <tbody>
                {data.items.map((p) => (
                  <tr key={p.id} className="hover:bg-surface-2/50">
                    <Td className="whitespace-nowrap text-xs text-muted">{p.fixture && kickoff(p.fixture.kickoff_at)}</Td>
                    <Td><Link href={`/matches/${p.fixture_id}`} className="font-medium hover:text-brand-400">{p.fixture?.home_team.name} vs {p.fixture?.away_team.name}</Link>
                      <p className="text-xs text-subtle">{p.fixture?.competition.name}{p.is_demo && " · demo"}</p></Td>
                    <Td className="whitespace-nowrap text-xs text-muted">{MARKET_LABEL[p.market]}</Td>
                    <Td className="text-right"><ProbabilityValue value={p.probability} /></Td>
                    <Td><CategoryBadge category={p.category} /></Td>
                    <Td className="tabular text-xs">{p.outcome?.home_score_at_cutoff != null ? `${p.outcome.home_score_at_cutoff}-${p.outcome.away_score_at_cutoff}` : "-"}</Td>
                    <Td><OutcomeBadge p={p} /></Td>
                    <Td className="whitespace-nowrap text-xs text-subtle">v{p.model.version}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pager page={data.page} pages={data.pages} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}
