"use client";

import { useState } from "react";
import { ArrowRight, Check, CheckCircle2, Copy, ExternalLink, XCircle } from "lucide-react";
import { Badge, CategoryBadge, QualityIndicator } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Stat } from "@/components/ui/data";
import { Alert } from "@/components/ui/feedback";
import { copyText, isConverted, oddsChangeText, STATUS_LABEL } from "@/lib/booking";
import { kickoff } from "@/lib/format";
import type { Conversion, ConversionSelection, ConversionStatus } from "@/lib/types";

const TONE: Record<ConversionStatus, "neutral" | "brand" | "warn" | "danger" | "info"> = {
  pending: "neutral", matched: "brand", odds_changed: "warn", unmatched: "danger", unavailable: "warn",
};

export function Warnings({ conv }: { conv: Conversion }) {
  if (!conv.warnings?.length) return null;
  return <div className="space-y-2">{conv.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}</div>;
}

/** What the model said about a ticket pick, next to the bookmaker's price. Estimates, never guarantees. */
export function AnalysisLine({ s, bookie }: { s: ConversionSelection; bookie: string }) {
  const a = s.analysis;
  if (!a) return null;
  return (
    <div className="mt-2 space-y-1.5 rounded-[var(--radius-md)] border border-border bg-surface-2/60 p-2.5 text-xs text-muted">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-fg">{a.market_label}</span>
        <CategoryBadge category={a.category} />
        <QualityIndicator quality={a.data_quality} />
      </div>
      <p>
        Model estimate <span className="tabular font-semibold text-fg">{(a.probability * 100).toFixed(1)}%</span>
        {a.fair_odds ? <> · fair odds <span className="tabular font-semibold text-fg">{a.fair_odds.toFixed(2)}</span></> : null}
        {a.bookmaker_odds ? <> · {bookie} odds <span className="tabular font-semibold text-fg">{a.bookmaker_odds}</span></> : null}
        {a.edge !== null && a.edge !== undefined ? <> · estimated edge <span className={a.edge > 0 ? "tabular font-semibold text-brand-400" : "tabular font-semibold text-muted"}>{(a.edge * 100).toFixed(1)}%</span></> : null}
      </p>
      <p className="text-subtle">{a.calibration_status === "calibrated" ? "Calibrated" : "Uncalibrated"} estimate from {a.model}; sample {a.sample} matches. Not a guarantee.</p>
    </div>
  );
}

export function StatusBadge({ status }: { status: ConversionStatus }) {
  return <Badge tone={TONE[status]}>{STATUS_LABEL[status]}</Badge>;
}

export function CopyButton({ text, label, variant = "primary" }: { text: string; label: string; variant?: "primary" | "outline" }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const click = async () => {
    const ok = await copyText(text);
    setState(ok ? "copied" : "failed");
    setTimeout(() => setState("idle"), 2500);
  };
  return (
    <div className="flex flex-col gap-1">
      <Button type="button" variant={variant} onClick={click} className="w-full sm:w-auto">
        {state === "copied" ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
        {state === "copied" ? "Copied" : label}
      </Button>
      <span role="status" className="text-xs text-danger">{state === "failed" ? "Couldn't copy automatically. Select the text and copy it by hand." : ""}</span>
    </div>
  );
}

export function BookingCard({ conv, onGenerate, busy }: { conv: Conversion; onGenerate: (partial: boolean) => void; busy: boolean }) {
  const b = conv.booking;
  const dest = conv.destination;
  const noneMatched = conv.counts.matched === 0;
  return (
    <Card className="border-brand-500/30">
      <CardHeader title={`${dest.name} booking code`} description={b?.status === "generated" ? "Created by the bookmaker for the matched selections." : undefined} />
      <CardBody className="space-y-4">
        {b?.status === "generated" && b.code && (
          <>
            {b.is_demo && <Alert tone="demo" title="Demo code - not a real bookmaker code">It came from the local demo simulator and will not work on any real bookmaker.</Alert>}
            <div className="flex items-center gap-2 text-brand-400"><CheckCircle2 className="h-5 w-5" aria-hidden /><span className="font-semibold">Conversion successful</span></div>
            <p className="select-all break-all rounded-[var(--radius-md)] border border-border-strong bg-surface-2 px-4 py-4 text-center font-[family-name:var(--font-mono)] text-2xl font-bold tracking-widest" aria-label="New booking code">{b.code}</p>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
              <CopyButton text={b.code} label="Copy booking code" />
              {b.share_url && <a className="text-sm text-brand-400 hover:underline" href={b.share_url} target="_blank" rel="noopener noreferrer">Open the shared slip <ExternalLink className="inline h-3.5 w-3.5" aria-hidden /></a>}
            </div>
            <p className="text-sm text-muted">Copy the code, then enter it on {dest.name}: look for “Booking code” or “Load code” on the betslip. Check every selection and price there before you bet.</p>
          </>
        )}
        {b?.status === "manual" && (
          <>
            <Alert tone="info" title="Recreate this slip on the bookmaker">{b.message}</Alert>
            {conv.betslip_text && <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-[var(--radius-md)] border border-border bg-surface-2 p-3 text-xs">{conv.betslip_text}</pre>}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
              {conv.betslip_text && <CopyButton text={conv.betslip_text} label="Copy slip as text" variant="outline" />}
              {dest.website && <a className="inline-flex h-10 items-center gap-1 text-sm text-brand-400 hover:underline" href={dest.website} target="_blank" rel="noopener noreferrer">Open {dest.name} <ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>}
            </div>
          </>
        )}
        {b?.status === "failed" && (
          <>
            <Alert tone="danger" title="No booking code was created">{b.message ?? `${dest.name} did not return a code.`} Your matched selections are listed below; nothing has been placed.</Alert>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Button type="button" onClick={() => onGenerate(true)} loading={busy}>Try again</Button>
              {conv.betslip_text && <CopyButton text={conv.betslip_text} label="Copy slip as text" variant="outline" />}
            </div>
          </>
        )}
        {!b && conv.state === "matched" && noneMatched && (
          <Alert tone="danger" title="Nothing could be converted">None of the selections could be matched at {dest.name}, so there is no slip to create. See the reasons below.</Alert>
        )}
        {!b && conv.state === "matched" && !noneMatched && conv.needs_decision && (
          <>
            <Alert tone="warn" title={`${conv.counts.original - conv.counts.matched} ${conv.counts.original - conv.counts.matched === 1 ? "selection" : "selections"} could not be converted`}>
              They are listed below with the reason. You can continue with the {conv.counts.matched} matched selection{conv.counts.matched === 1 ? "" : "s"}, but the new slip will not be the same bet. Nothing is removed without your say-so.
            </Alert>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Button type="button" onClick={() => onGenerate(true)} loading={busy}>Continue with {conv.counts.matched} matched</Button>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

export function SummaryStats({ conv }: { conv: Conversion }) {
  const c = conv.counts;
  const notConverted = c.unmatched + c.unavailable;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat label="Original selections" value={c.original} sub={`${conv.source.name} → ${conv.destination.name}`} />
      <Stat label="Matched" value={c.matched} tone="brand" icon={CheckCircle2} sub={c.odds_changed ? `${c.odds_changed} with changed odds` : "Odds unchanged"} />
      <Stat label="Not converted" value={notConverted} tone={notConverted ? "warn" : "default"} icon={notConverted ? XCircle : undefined}
        sub={notConverted ? `${c.unmatched} unmatched · ${c.unavailable} unavailable` : "None"} />
      <Stat label="Total odds" value={conv.totals.destination_odds ?? "-"} sub={conv.totals.original_odds ? `Original ${conv.totals.original_odds}${conv.totals.destination_covers_all ? "" : " (all legs)"}` : undefined} />
    </div>
  );
}

function Fixture({ home, away, comp, start }: { home: string; away: string; comp: string | null; start: string | null }) {
  return (
    <div className="min-w-0">
      <p className="break-words font-medium">{home} vs {away}</p>
      <p className="text-xs text-subtle">{[comp, start ? kickoff(start) : null].filter(Boolean).join(" · ")}</p>
    </div>
  );
}

function OddsCell({ s }: { s: ConversionSelection }) {
  const change = oddsChangeText(s.odds);
  return (
    <div className="tabular text-right">
      <p className="font-semibold">{s.odds.destination ?? "-"}</p>
      {s.odds.original && <p className="text-xs text-subtle">was {s.odds.original}</p>}
      {change && <p className={s.odds.change === "up" ? "text-xs text-brand-400" : "text-xs text-warn"}><span className="sr-only">Odds changed: </span>{s.odds.change === "up" ? "▲ higher" : "▼ lower"}</p>}
    </div>
  );
}

function Destination({ s }: { s: ConversionSelection }) {
  if (!isConverted(s) || !s.destination) {
    return <p className="text-sm text-muted">{s.reason ?? "Not converted."}</p>;
  }
  return (
    <div className="min-w-0 space-y-0.5">
      <Fixture home={s.destination.home_team} away={s.destination.away_team} comp={s.destination.competition} start={s.destination.start_time} />
      <p className="text-sm">{s.destination.market_name}: <span className="font-semibold">{s.destination.outcome}</span></p>
      {s.confidence === "medium" && <p className="text-xs text-warn">Please double-check this fixture: the team names or kick-off differ slightly.</p>}
    </div>
  );
}

export function SelectionsList({ conv }: { conv: Conversion }) {
  const hasDest = conv.state !== "decoded";
  return (
    <Card>
      <CardHeader title="Selections" description={hasDest ? "Original on the left, destination on the right." : "Original selections"} />
      {/* Phones: one card per selection. */}
      <ul className="divide-y divide-border md:hidden">
        {conv.selections.map((s) => (
          <li key={s.index} className="space-y-3 p-4">
            <div className="flex items-start justify-between gap-2">
              <Fixture home={s.source.home_team} away={s.source.away_team} comp={s.source.competition} start={s.source.start_time} />
              <StatusBadge status={s.status} />
            </div>
            <p className="text-sm"><span className="text-muted">{s.source.market_name}:</span> <span className="font-semibold">{s.source.outcome}</span> {s.source.odds && <span className="tabular text-subtle">@ {s.source.odds}</span>}</p>
            {hasDest && (
              <div className="rounded-[var(--radius-md)] border border-border bg-surface-2 p-3">
                <p className="mb-1 flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-subtle"><ArrowRight className="h-3 w-3" aria-hidden />{conv.destination.name}</p>
                <div className="flex items-start justify-between gap-3">
                  <Destination s={s} />
                  {isConverted(s) && <OddsCell s={s} />}
                </div>
              </div>
            )}
            <AnalysisLine s={s} bookie={conv.destination.name} />
          </li>
        ))}
      </ul>
      {/* Tablets and desktops: a table. */}
      <div className="hidden md:block">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-subtle">
            <tr><th className="px-5 py-3 font-medium">{conv.source.name}</th><th className="px-3 py-3 font-medium">{conv.destination.name}</th><th className="px-3 py-3 text-right font-medium">Odds</th><th className="px-5 py-3 font-medium">Status</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {conv.selections.map((s) => (
              <tr key={s.index} className="align-top">
                <td className="px-5 py-3"><Fixture home={s.source.home_team} away={s.source.away_team} comp={s.source.competition} start={s.source.start_time} />
                  <p className="mt-1 text-sm"><span className="text-muted">{s.source.market_name}:</span> <span className="font-semibold">{s.source.outcome}</span></p>
                  <AnalysisLine s={s} bookie={conv.destination.name} /></td>
                <td className="px-3 py-3">{hasDest ? <Destination s={s} /> : <span className="text-muted">-</span>}</td>
                <td className="px-3 py-3">{isConverted(s) ? <OddsCell s={s} /> : <p className="tabular text-right text-subtle">{s.odds.original ?? "-"}</p>}</td>
                <td className="px-5 py-3"><StatusBadge status={s.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
