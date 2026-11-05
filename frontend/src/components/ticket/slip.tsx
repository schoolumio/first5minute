"use client";

import { AlertCircle, Check, CheckCircle2, ChevronRight, Trash2 } from "lucide-react";
import { Badge, CategoryBadge, QualityIndicator } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { kickoff, relative } from "@/lib/format";
import type { TicketItem } from "@/lib/ticket";
import type { ConversionSelection, ConverterBookmaker, TicketPreviewItem } from "@/lib/types";
import { ProbabilityRing } from "./ring";

const MARKET_NAME = { MARKET_A: "No goal in the first 5 minutes", MARKET_B: "Level at 5 minutes" } as const;
const STRIPE = { MARKET_A: "bg-brand-500", MARKET_B: "bg-info" } as const;

export function Stepper({ step }: { step: 1 | 2 | 3 }) {
  const steps = ["Pick games", "Choose bookmaker", "Get your code"];
  return (
    <ol className="mb-6 flex items-center gap-2 text-xs sm:text-sm" aria-label="Progress">
      {steps.map((label, i) => {
        const n = i + 1;
        const done = n < step, active = n === step;
        return (
          <li key={label} className="flex items-center gap-2" aria-current={active ? "step" : undefined}>
            <span className={cn("flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-bold",
              done ? "border-brand-500 bg-brand-500 text-[#06110a]" : active ? "border-brand-500 text-brand-400" : "border-border-strong text-subtle")}>
              {done ? <Check className="h-3.5 w-3.5" aria-hidden /> : n}
            </span>
            <span className={cn("font-medium", active ? "text-fg" : done ? "text-muted" : "text-subtle", !active && "hidden sm:inline")}>{label}</span>
            {n < 3 && <ChevronRight className="h-4 w-4 text-border-strong" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}

function Frame({ market, children, tone }: { market: TicketItem["market"]; children: React.ReactNode; tone?: "bad" }) {
  return (
    <div className={cn("relative overflow-hidden rounded-[var(--radius-lg)] border bg-surface shadow-[var(--shadow-card)]", tone === "bad" ? "border-danger/40" : "border-border")}>
      <span className={cn("absolute inset-y-0 left-0 w-1", tone === "bad" ? "bg-danger" : STRIPE[market])} aria-hidden />
      <div className="p-4 pl-5">{children}</div>
    </div>
  );
}

/** A game on the ticket, before generating: the pick and the model's reasoning. */
export function SlipLeg({ item, info, onRemove }: { item: TicketItem; info?: TicketPreviewItem; onRemove: () => void }) {
  const fresh = info && info.probability !== undefined ? info : null;
  const prob = fresh?.probability ?? item.probability;
  const blocked = info && !info.available;
  return (
    <Frame market={item.market} tone={blocked ? "bad" : undefined}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[11px] font-medium uppercase tracking-wide text-subtle">{item.competition} · {kickoff(item.kickoff_at)} <span className="normal-case">({relative(item.kickoff_at)})</span>{item.is_demo && <Badge tone="demo" className="ml-2">Demo</Badge>}</p>
          <p className="mt-1 break-words text-[15px] font-semibold leading-snug">{item.home} <span className="font-normal text-muted">vs</span> {item.away}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-surface-3 px-2.5 py-1 text-xs font-semibold">{MARKET_NAME[item.market]}</span>
            <CategoryBadge category={fresh?.category ?? item.category} />
            {fresh?.data_quality && <QualityIndicator quality={fresh.data_quality} />}
          </div>
          {fresh && (
            <p className="mt-2 text-xs leading-relaxed text-muted">
              {fresh.fair_odds ? <>Fair odds <b className="tabular text-fg">{fresh.fair_odds.toFixed(2)}</b> · </> : null}
              Confidence <b className="capitalize text-fg">{fresh.confidence}</b> · <b className="tabular text-fg">{fresh.sample}</b>-match sample ·{" "}
              {fresh.calibration_status === "calibrated" ? "calibrated" : "uncalibrated"} estimate
            </p>
          )}
          {blocked && <p className="mt-2 flex items-start gap-1.5 text-xs text-danger"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />{info?.reason}</p>}
        </div>
        <div className="flex flex-col items-center gap-1">
          <ProbabilityRing value={prob} />
          <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${item.home} vs ${item.away}`} onClick={onRemove}><Trash2 className="h-4 w-4" aria-hidden /></Button>
        </div>
      </div>
    </Frame>
  );
}

/** A game on the ticket after we checked it at the chosen bookmaker: what was added, at what price, or why not. */
export function SlipResultLeg({ s, bookie }: { s: ConversionSelection; bookie: string }) {
  const a = s.analysis;
  const ok = s.status === "matched" || s.status === "odds_changed";
  const market = (a?.market ?? "MARKET_A") as TicketItem["market"];
  const edge = a?.edge ?? null;
  return (
    <Frame market={market} tone={ok ? undefined : "bad"}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[11px] font-medium uppercase tracking-wide text-subtle">{s.source.competition} · {s.source.start_time ? kickoff(s.source.start_time) : ""}</p>
          <p className="mt-1 break-words text-[15px] font-semibold leading-snug">{s.source.home_team} <span className="font-normal text-muted">vs</span> {s.source.away_team}</p>
          <p className="mt-1.5 text-sm"><span className="font-semibold">{a?.market_label ?? s.source.market_name}</span></p>
          {ok && s.destination ? (
            <p className="mt-1 flex items-start gap-1.5 text-xs text-muted"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-400" aria-hidden />
              Added at {bookie} as <b className="text-fg">{s.destination.market_name}: {s.destination.outcome}</b></p>
          ) : (
            <p className="mt-1 flex items-start gap-1.5 text-xs text-danger"><AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />Not added: {s.reason}</p>
          )}
          {ok && s.confidence === "medium" && <p className="mt-1 text-xs text-warn">Check this game on {bookie}: the team names or kick-off differ slightly.</p>}
          {a && <div className="mt-2 flex flex-wrap items-center gap-2"><CategoryBadge category={a.category} /><QualityIndicator quality={a.data_quality} /></div>}
          {a && <p className="mt-2 text-xs text-muted">Model <b className="tabular text-fg">{(a.probability * 100).toFixed(1)}%</b>{a.fair_odds ? <> · fair odds <b className="tabular text-fg">{a.fair_odds.toFixed(2)}</b></> : null} · {a.calibration_status === "calibrated" ? "calibrated" : "uncalibrated"} estimate</p>}
        </div>
        <div className="shrink-0 text-right">
          {ok && s.destination?.odds ? (
            <>
              <p className="text-[10px] font-medium uppercase tracking-wide text-subtle">{bookie}</p>
              <p className="tabular font-[family-name:var(--font-mono)] text-xl font-bold">{s.destination.odds}</p>
              {edge !== null && <p className={cn("tabular text-[11px] font-semibold", edge > 0 ? "text-brand-400" : "text-muted")}>{edge > 0 ? "+" : ""}{(edge * 100).toFixed(1)}% vs model</p>}
            </>
          ) : <Badge tone={s.status === "unmatched" ? "danger" : "warn"}>{s.status === "unmatched" ? "Not found" : "Unavailable"}</Badge>}
        </div>
      </div>
    </Frame>
  );
}

/** Pick the bookmaker: tiles rather than a dropdown, with plain-language capability. */
export function BookieTiles({ bookmakers, value, onChange }: { bookmakers: ConverterBookmaker[]; value: string; onChange: (code: string) => void }) {
  return (
    <div role="radiogroup" aria-label="Your bookmaker" className="grid grid-cols-2 gap-2">
      {bookmakers.map((b) => {
        const usable = b.can_be_destination;
        const sel = value === b.code;
        return (
          <button key={b.code} type="button" role="radio" aria-checked={sel} disabled={!usable} onClick={() => onChange(b.code)}
            className={cn("min-h-16 cursor-pointer rounded-[var(--radius-md)] border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              sel ? "border-brand-500 bg-brand-500/10" : "border-border-strong bg-surface-2 hover:border-brand-500/50")}>
            <span className="flex items-center justify-between gap-2">
              <span className="break-words text-sm font-semibold">{b.name}</span>
              {sel && <Check className="h-4 w-4 shrink-0 text-brand-400" aria-hidden />}
            </span>
            <span className="mt-0.5 block text-[11px] text-muted">
              {!usable ? "Not connected yet" : b.can_generate ? "Booking code" : "Slip to copy"}{b.is_demo ? " · demo" : ""}
            </span>
          </button>
        );
      })}
    </div>
  );
}
