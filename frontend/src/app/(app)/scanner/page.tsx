"use client";

import { Lock, Radar, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/app-shell";
import { MatchPickCard } from "@/components/match/match-pick-card";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Pager, Tabs } from "@/components/ui/data";
import { Alert, EmptyState, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { useAuth } from "@/lib/auth";
import { CATEGORY_LABEL } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Category, Competition, Prediction } from "@/lib/types";

interface ScannerRes {
  items: Prediction[]; total: number; page: number; pages: number; locked_count: number; plan: string;
  counts: Record<string, number>; window: { from: string; to: string }; is_demo: boolean;
}

const DEFAULTS = {
  date_from: "", date_to: "", market: "", competition_id: "", gender: "", min_probability: "",
  country: "", competition_type: "", min_sample: "", min_data_quality: "", team: "", sort: "probability",
};

export default function ScannerPage() {
  const { has } = useAuth();
  const advanced = has("advanced_filters");
  const odds = has("odds_comparison");
  const [draft, setDraft] = useState(DEFAULTS);
  const [filters, setFilters] = useState(DEFAULTS);
  const [categories, setCategories] = useState<Category[]>(["qualified", "watchlist"]);
  const [page, setPage] = useState(1);
  const [showFilters, setShowFilters] = useState(false);
  const comps = useApi<Competition[]>("/competitions");

  const query = useMemo(() => {
    const q: Record<string, string | number | string[]> = { page, page_size: 24, categories };
    for (const [k, v] of Object.entries(filters)) if (v !== "") q[k] = k === "min_probability" ? Number(v) / 100 : v;
    return q;
  }, [filters, categories, page]);
  const { data, loading, error } = useApi<ScannerRes>("/scanner", query);
  // one card per game with both five-minute picks side by side
  const groups = useMemo(() => {
    const byFixture = new Map<number, { fixture: NonNullable<Prediction["fixture"]>; a?: Prediction; b?: Prediction }>();
    for (const p of data?.items ?? []) {
      if (!p.fixture) continue;
      const g = byFixture.get(p.fixture_id) ?? { fixture: p.fixture };
      if (p.market === "MARKET_A") g.a = p; else g.b = p;
      byFixture.set(p.fixture_id, g);
    }
    return [...byFixture.values()];
  }, [data]);

  const set = (k: keyof typeof DEFAULTS) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setDraft({ ...draft, [k]: e.target.value });
  const apply = (e?: React.FormEvent) => { e?.preventDefault(); setPage(1); setFilters(draft); };
  const reset = () => { setDraft(DEFAULTS); setFilters(DEFAULTS); setPage(1); };
  const quick = (k: keyof typeof DEFAULTS, v: string) => { setPage(1); setDraft((d) => ({ ...d, [k]: v })); setFilters((f) => ({ ...f, [k]: v })); };
  const countries = Array.from(new Set((comps.data ?? []).map((c) => c.country).filter(Boolean))) as string[];

  const LockedField = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <Field label={label}>
      {advanced ? children : (
        <Link href="/pricing" className="flex h-10 items-center gap-2 rounded-[var(--radius-md)] border border-dashed border-border-strong px-3 text-xs text-subtle hover:text-fg">
          <Lock className="h-3.5 w-3.5" /> Pro filter
        </Link>
      )}
    </Field>
  );

  return (
    <>
      <PageHeader
        eyebrow="Opportunity radar"
        title="Match scanner"
        description="Upcoming fixtures ranked by model-estimated probability, sample size and data quality. Tap the picks you like to build a ticket."
      />

      <div className="panel mb-4 flex flex-wrap items-center gap-x-5 gap-y-3 rounded-[var(--radius-lg)] px-4 py-3">
        <Tabs value={(filters.market || "") as "" | "MARKET_A" | "MARKET_B"} onChange={(m) => quick("market", m)}
          options={[{ value: "", label: "Both markets" }, { value: "MARKET_A", label: "No goal 0-5'" }, { value: "MARKET_B", label: "Level at 5'" }]} />
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Tiers">
          {(["qualified", "watchlist", "below_threshold", "excluded"] as Category[]).map((c) => {
            const on = categories.includes(c);
            return (
              <button key={c} type="button" aria-pressed={on} onClick={() => { setPage(1); setCategories(on ? categories.filter((x) => x !== c) : [...categories, c]); }}
                className={`cursor-pointer rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${on ? "border-brand-500/50 bg-brand-500/10 text-brand-300" : "border-border-strong text-muted hover:text-fg"}`}>
                {CATEGORY_LABEL[c]}{data?.counts?.[c] !== undefined && <span className="numeral ml-1.5 text-muted">{data.counts[c]}</span>}
              </button>
            );
          })}
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto">
          <Select aria-label="Sort by" className="h-8 w-40 min-w-0 flex-1 text-xs sm:flex-none sm:w-44" value={filters.sort} onChange={(e) => quick("sort", e.target.value)}>
            <option value="probability">Sort: probability</option>
            <option value="kickoff">Sort: kick-off</option>
            <option value="competition">Sort: competition</option>
            <option value="value" disabled={!odds}>Sort: value {odds ? "" : "(Pro)"}</option>
          </Select>
          <Button variant="outline" size="sm" onClick={() => setShowFilters(!showFilters)}><SlidersHorizontal className="h-4 w-4" /> {showFilters ? "Hide" : "More"} filters</Button>
        </div>
      </div>

      {showFilters && (
        <Card className="mb-5">
          <CardBody>
            <form onSubmit={apply} className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
              <Field label="From date"><Input type="date" value={draft.date_from} onChange={set("date_from")} /></Field>
              <Field label="To date"><Input type="date" value={draft.date_to} onChange={set("date_to")} /></Field>
              <Field label="Competition">
                <Select value={draft.competition_id} onChange={set("competition_id")}>
                  <option value="">All competitions</option>
                  {(comps.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </Select>
              </Field>
              <Field label="Football">
                <Select value={draft.gender} onChange={set("gender")}>
                  <option value="">Men&apos;s & women&apos;s</option>
                  <option value="men">Men&apos;s</option>
                  <option value="women">Women&apos;s</option>
                </Select>
              </Field>
              <Field label="Min. probability %"><Input type="number" min={50} max={99.9} step={0.5} placeholder="e.g. 88" value={draft.min_probability} onChange={set("min_probability")} /></Field>
              <LockedField label="Country">
                <Select value={draft.country} onChange={set("country")}>
                  <option value="">All countries</option>
                  {countries.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </LockedField>
              <LockedField label="Competition type">
                <Select value={draft.competition_type} onChange={set("competition_type")}>
                  <option value="">Any type</option>
                  <option value="league">Domestic league</option>
                  <option value="cup">Cup</option>
                  <option value="continental">Continental</option>
                  <option value="international">International</option>
                </Select>
              </LockedField>
              <LockedField label="Min. team sample"><Input type="number" min={0} max={100} value={draft.min_sample} onChange={set("min_sample")} /></LockedField>
              <LockedField label="Data quality">
                <Select value={draft.min_data_quality} onChange={set("min_data_quality")}>
                  <option value="">Any</option>
                  <option value="low">Low or better</option>
                  <option value="medium">Medium or better</option>
                  <option value="high">High only</option>
                </Select>
              </LockedField>
              <LockedField label="Home / away team"><Input placeholder="Team name" value={draft.team} onChange={set("team")} maxLength={80} /></LockedField>
              <div className="col-span-2 flex flex-wrap items-center gap-4 md:col-span-4 xl:col-span-6">
                <div className="ml-auto flex gap-2">
                  <Button type="button" variant="ghost" size="sm" onClick={reset}>Reset</Button>
                  <Button type="submit" size="sm">Apply filters</Button>
                </div>
              </div>
            </form>
          </CardBody>
        </Card>
      )}

      {error && <Alert tone={error.status === 402 ? "warn" : "danger"} className="mb-4">{error.message}</Alert>}

      {data && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <p>
            <span className="font-semibold text-fg">{groups.length}</span> games · <span className="font-semibold text-fg">{data.total}</span> predictions ·{" "}
            {Object.entries(data.counts).map(([k, v]) => `${CATEGORY_LABEL[k as Category]} ${v}`).join(" · ") || "none"}
          </p>
          <p>Window {new Date(data.window.from).toLocaleString()} - {new Date(data.window.to).toLocaleString()}</p>
        </div>
      )}

      {loading ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-48" />)}</div>
      ) : !data?.items.length ? (
        <Card><EmptyState icon={Radar} title="No matches for these filters">Try widening the date range, lowering the probability threshold or including the watchlist.</EmptyState></Card>
      ) : (
        <>
          <p className="mb-3 text-xs text-muted">Tap a pick to add it to your ticket (one pick per game), then review it in <Link href="/ticket" className="font-semibold text-brand-400 hover:underline">My ticket</Link>.</p>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {groups.map((g) => <MatchPickCard key={g.fixture.id} fixture={g.fixture} a={g.a} b={g.b} />)}
          </div>
          <Pager page={data.page} pages={data.pages} onPage={setPage} />
        </>
      )}

      {data && data.locked_count > 0 && (
        <Alert tone="info" className="mt-4" title={`${data.locked_count} more matches on paid plans`}>
          The Free plan shows the top {data.items.length} matches by probability each day. <Link href="/pricing" className="font-semibold underline">Compare plans</Link>
        </Alert>
      )}
      <p className="mt-6 text-xs text-subtle">
        Probabilities are uncalibrated outputs of the baseline Poisson models and carry substantial uncertainty in five-minute windows.
        They are not betting advice. 18+.
      </p>
    </>
  );
}
