"use client";

import { Lock, Radar, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/app-shell";
import { PredictionCard } from "@/components/match/prediction-row";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Pager } from "@/components/ui/data";
import { Alert, EmptyState, Skeleton } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
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
  const [showFilters, setShowFilters] = useState(true);
  const comps = useApi<Competition[]>("/competitions");

  const query = useMemo(() => {
    const q: Record<string, string | number | string[]> = { page, page_size: 24, categories };
    for (const [k, v] of Object.entries(filters)) if (v !== "") q[k] = k === "min_probability" ? Number(v) / 100 : v;
    return q;
  }, [filters, categories, page]);
  const { data, loading, error } = useApi<ScannerRes>("/scanner", query);

  const set = (k: keyof typeof DEFAULTS) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setDraft({ ...draft, [k]: e.target.value });
  const apply = (e?: React.FormEvent) => { e?.preventDefault(); setPage(1); setFilters(draft); };
  const reset = () => { setDraft(DEFAULTS); setFilters(DEFAULTS); setPage(1); };
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
        title="Match scanner"
        description="Upcoming fixtures ranked by model-estimated probability, sample size and data quality."
        action={<Button variant="outline" size="sm" onClick={() => setShowFilters(!showFilters)}><SlidersHorizontal className="h-4 w-4" /> {showFilters ? "Hide" : "Show"} filters</Button>}
      />

      {showFilters && (
        <Card className="mb-5">
          <CardBody>
            <form onSubmit={apply} className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
              <Field label="From date"><Input type="date" value={draft.date_from} onChange={set("date_from")} /></Field>
              <Field label="To date"><Input type="date" value={draft.date_to} onChange={set("date_to")} /></Field>
              <Field label="Market">
                <Select value={draft.market} onChange={set("market")}>
                  <option value="">Both markets</option>
                  <option value="MARKET_A">A · No goal 0-5&apos;</option>
                  <option value="MARKET_B">B · Level at 5&apos;</option>
                </Select>
              </Field>
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
              <Field label="Sort by">
                <Select value={draft.sort} onChange={set("sort")}>
                  <option value="probability">Probability</option>
                  <option value="kickoff">Kick-off time</option>
                  <option value="competition">Competition</option>
                  <option value="value" disabled={!odds}>Available value {odds ? "" : "(Pro)"}</option>
                </Select>
              </Field>
              <div className="col-span-2 flex flex-wrap items-center gap-4 md:col-span-4 xl:col-span-6">
                {(["qualified", "watchlist", "below_threshold", "excluded"] as Category[]).map((c) => (
                  <Checkbox key={c} label={CATEGORY_LABEL[c]} checked={categories.includes(c)}
                    onChange={(e) => { setPage(1); setCategories(e.target.checked ? [...categories, c] : categories.filter((x) => x !== c)); }} />
                ))}
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
            <span className="font-semibold text-fg">{data.total}</span> predictions ·{" "}
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
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{data.items.map((p) => <PredictionCard key={p.id} p={p} />)}</div>
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
