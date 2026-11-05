"use client";

import Link from "next/link";
import { Check } from "lucide-react";
import { Badge, CategoryBadge, DemoBadge, QualityIndicator } from "@/components/ui/badge";
import { ProbabilityBar, ProbabilityValue } from "@/components/ui/data";
import { cn } from "@/lib/cn";
import { kickoff, minSample, relative } from "@/lib/format";
import { itemFromPrediction, useTicket } from "@/lib/ticket";
import type { Fixture, Market, Prediction } from "@/lib/types";

const TILE: Record<Market, { title: string; sub: string }> = {
  MARKET_A: { title: "No goal 0-5'", sub: "0-0 after 5 min" },
  MARKET_B: { title: "Level at 5'", sub: "Level after 5 min" },
};

function PickTile({ market, p }: { market: Market; p?: Prediction }) {
  const { has, toggle } = useTicket();
  const t = TILE[market];
  if (!p) {
    return <div className="rounded-[var(--radius-md)] border border-dashed border-border p-3 text-xs text-subtle"><p className="font-semibold">{t.title}</p><p className="mt-1">Not in your current filters.</p></div>;
  }
  const started = !!p.fixture && new Date(p.fixture.kickoff_at).getTime() <= Date.now();
  const blocked = p.category === "excluded" || started;
  const on = has(p.id);
  return (
    <button type="button" data-pick={p.id} aria-pressed={on} disabled={blocked} title={p.category === "excluded" ? p.category_reasons[0] : undefined}
      onClick={() => { const item = itemFromPrediction(p); if (item) toggle(item); }}
      className={cn("group relative w-full cursor-pointer rounded-[var(--radius-md)] border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        on ? "border-brand-500 bg-brand-500/10" : "border-border-strong bg-surface-2 hover:border-brand-500/60")}>
      <span className="flex items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="block truncate text-xs font-semibold">{t.title}</span>
          <span className="block truncate text-[11px] text-subtle">{t.sub}</span>
        </span>
        <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-on-brand", on ? "border-brand-500 bg-brand-500" : "border-border-strong text-transparent group-hover:border-brand-500/60")} aria-hidden>
          <Check className="h-3 w-3" />
        </span>
      </span>
      <ProbabilityValue value={p.probability} className="mt-2 block text-2xl" />
      <ProbabilityBar value={p.probability} className="mt-2" />
      <span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
        <CategoryBadge category={p.category} />
        <QualityIndicator quality={p.data_quality} compact />
        <span className="text-[11px] text-subtle">{minSample(p)} matches</span>
      </span>
      <span className="mt-2 block text-[11px] font-semibold text-brand-400">{blocked ? (started ? "Already started" : "Not enough data") : on ? "On your ticket" : "Tap to add to ticket"}</span>
    </button>
  );
}

/** One game with both five-minute picks side by side: read the analysis, tap the pick you want. */
export function MatchPickCard({ fixture, a, b }: { fixture: Fixture; a?: Prediction; b?: Prediction }) {
  const demo = (a ?? b)?.is_demo;
  return (
    <article className="min-w-0 overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface shadow-[var(--shadow-card)]">
      <header className="px-4 pt-4">
        <p className="flex flex-wrap items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-subtle">
          <span className="truncate">{fixture.competition.name}</span>
          {fixture.competition.gender === "women" && <Badge tone="info">Women</Badge>}
          {demo && <DemoBadge />}
        </p>
        <Link href={`/matches/${fixture.id}`} className="mt-1.5 block break-words text-[15px] font-semibold leading-snug hover:text-brand-400">
          {fixture.home_team.name} <span className="font-normal text-muted">vs</span> {fixture.away_team.name}
        </Link>
        <p className="mt-0.5 text-xs text-muted">{kickoff(fixture.kickoff_at)} <span className="text-subtle">· {relative(fixture.kickoff_at)}</span></p>
      </header>
      <div className="grid grid-cols-2 gap-2 p-3">
        <PickTile market="MARKET_A" p={a} />
        <PickTile market="MARKET_B" p={b} />
      </div>
      <footer className="flex items-center justify-between border-t border-border px-4 py-2 text-[11px] text-subtle">
        <span>Estimates, not guarantees</span>
        <Link href={`/matches/${fixture.id}`} className="font-semibold text-muted hover:text-fg">Full analysis →</Link>
      </footer>
    </article>
  );
}
