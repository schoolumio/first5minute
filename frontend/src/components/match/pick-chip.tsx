"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/cn";
import { pct } from "@/lib/format";
import { itemFromPrediction, useTicket } from "@/lib/ticket";
import type { Market, Prediction } from "@/lib/types";

const SHORT: Record<Market, string> = { MARKET_A: "No goal 0-5'", MARKET_B: "Level at 5'" };

/** Compact tappable probability: the estimate for one market, and one tap to put it on the ticket. */
export function PickChip({ market, p, className }: { market: Market; p?: Prediction; className?: string }) {
  const { has, toggle } = useTicket();
  if (!p) return <div className={cn("flex min-h-14 items-center justify-center rounded-[var(--radius-md)] border border-dashed border-border px-3 text-[11px] text-subtle", className)}>{SHORT[market]} · n/a</div>;
  const on = has(p.id);
  const blocked = p.category === "excluded" || (!!p.fixture && new Date(p.fixture.kickoff_at).getTime() <= Date.now());
  const tone = p.category === "qualified" ? "bg-brand-500" : p.category === "watchlist" ? "bg-info" : "bg-subtle";
  return (
    <button type="button" data-pick={p.id} aria-pressed={on} disabled={blocked}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); const i = itemFromPrediction(p); if (i) toggle(i); }}
      className={cn("group relative min-h-14 min-w-[8.5rem] cursor-pointer overflow-hidden rounded-[var(--radius-md)] border px-3 py-2 text-left transition-all disabled:cursor-not-allowed disabled:opacity-50",
        on ? "border-brand-500 bg-brand-500/10 shadow-[var(--shadow-glow)]" : "border-border-strong bg-bg/50 hover:border-brand-500/60", className)}>
      <span className={cn("absolute inset-y-0 left-0 w-[3px]", tone)} aria-hidden />
      <span className="flex items-center justify-between gap-2">
        <span className="font-[family-name:var(--font-mono)] text-[10px] font-semibold uppercase tracking-wider text-muted">{SHORT[market]}</span>
        <span className={cn("flex h-4 w-4 items-center justify-center rounded-full border", on ? "border-brand-500 bg-brand-500 text-on-brand" : "border-border-strong text-transparent")} aria-hidden><Check className="h-2.5 w-2.5" /></span>
      </span>
      <span className="numeral mt-0.5 block text-[26px] leading-none">{pct(p.probability)}</span>
    </button>
  );
}
