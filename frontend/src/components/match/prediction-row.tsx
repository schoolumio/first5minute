"use client";

import Link from "next/link";
import { Bookmark, BookmarkCheck } from "lucide-react";
import { useState } from "react";
import { Badge, CategoryBadge, DemoBadge, QualityIndicator } from "@/components/ui/badge";
import { ProbabilityBar, ProbabilityValue } from "@/components/ui/data";
import { AddToTicketButton } from "@/components/ticket/add-button";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { kickoff, MARKET_LABEL, minSample, relative } from "@/lib/format";
import type { Prediction } from "@/lib/types";

export function OutcomeBadge({ p }: { p: Prediction }) {
  if (!p.outcome) return <Badge>Pending</Badge>;
  const r = p.outcome.result;
  const tone = r === "won" ? "brand" : r === "lost" ? "danger" : "warn";
  const label = r === "won" ? "Correct" : r === "lost" ? "Incorrect" : r === "void" ? "Void" : "Unresolved";
  return <Badge tone={tone} title={p.outcome.notes ?? undefined}>{label}</Badge>;
}

export function PredictionCard({ p, threshold, saved: initialSaved = false }: { p: Prediction; threshold?: number; saved?: boolean }) {
  const fx = p.fixture!;
  const [saved, setSaved] = useState(initialSaved);
  const save = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (!saved) {
      await api("/saved-matches", { method: "POST", body: { fixture_id: fx.id } }).catch(() => undefined);
      setSaved(true);
    }
  };
  return (
    <Link href={`/matches/${fx.id}`}
      className="group block min-w-0 rounded-[var(--radius-lg)] border border-border bg-surface p-4 transition-colors hover:border-border-strong hover:bg-surface-2/60">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-subtle">
            <span className="truncate">{fx.competition.name}</span>
            {fx.competition.gender === "women" && <Badge tone="info">Women</Badge>}
            {p.is_demo && <DemoBadge />}
          </p>
          <p className="mt-1.5 truncate text-[15px] font-semibold">
            {fx.home_team.name} <span className="font-normal text-muted">vs</span> {fx.away_team.name}
          </p>
          <p className="mt-0.5 text-xs text-muted">
            {kickoff(fx.kickoff_at)} <span className="text-subtle">· {relative(fx.kickoff_at)}</span>
          </p>
        </div>
        <button onClick={save} className="cursor-pointer rounded-full p-1.5 text-muted hover:bg-surface-3 hover:text-fg"
          aria-label={saved ? "Saved" : "Save match"}>
          {saved ? <BookmarkCheck className="h-4 w-4 text-brand-400" /> : <Bookmark className="h-4 w-4" />}
        </button>
      </div>
      <div className="mt-4 flex items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-subtle">{MARKET_LABEL[p.market]}</p>
          <ProbabilityValue value={p.probability} className="text-2xl" />
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <CategoryBadge category={p.category} />
          {p.best_odds && (
            <span className="text-xs text-muted">
              Best odds <span className="tabular font-semibold text-fg">{p.best_odds.decimal_odds.toFixed(2)}</span>{p.best_odds.is_demo && <span className="ml-1 text-demo">(demo)</span>}
            </span>
          )}
        </div>
      </div>
      {p.category === "excluded" && p.category_reasons[0] && (
        <p className="mt-3 rounded-[var(--radius-sm)] border border-danger/30 bg-danger/5 px-2.5 py-1.5 text-xs text-danger">{p.category_reasons[0]}</p>
      )}
      <ProbabilityBar value={p.probability} threshold={threshold} className="mt-3" />
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span>Confidence <span className={cn("font-semibold capitalize", p.confidence === "high" ? "text-brand-400" : p.confidence === "medium" ? "text-info" : "text-warn")}>{p.confidence}</span></span>
        <span>Sample <span className="tabular font-semibold text-fg">{minSample(p)}</span> matches</span>
        <QualityIndicator quality={p.data_quality} />
        {p.edge !== undefined && p.edge !== null && (
          <span>Model edge <span className={cn("tabular font-semibold", p.edge > 0 ? "text-brand-400" : "text-muted")}>{(p.edge * 100).toFixed(1)}%</span></span>
        )}
      </div>
      <div className="mt-3 flex justify-end"><AddToTicketButton p={p} /></div>
    </Link>
  );
}
