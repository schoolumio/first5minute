"use client";

import { Check, Plus, Repeat2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { itemFromPrediction, useTicket } from "@/lib/ticket";
import type { Prediction } from "@/lib/types";

/** "Add to ticket" for one scanner pick. One pick per game: choosing the other market swaps the pick. */
export function AddToTicketButton({ p, className }: { p: Prediction; className?: string }) {
  const { has, hasFixture, toggle } = useTicket();
  const fx = p.fixture;
  const started = !!fx && new Date(fx.kickoff_at).getTime() <= Date.now();
  const blocked = p.category === "excluded" || started || !fx;
  const on = has(p.id);
  const swap = !on && !!fx && hasFixture(fx.id);
  const label = on ? "On your ticket" : swap ? "Use this pick instead" : "Add to ticket";
  const reason = p.category === "excluded" ? "Excluded: not enough reliable data" : started ? "Already started" : undefined;
  return (
    <Button type="button" size="sm" variant={on ? "primary" : "outline"} aria-pressed={on} disabled={blocked} title={reason}
      className={cn("min-h-9", className)}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); const item = itemFromPrediction(p); if (item) toggle(item); }}>
      {on ? <Check className="h-3.5 w-3.5" aria-hidden /> : swap ? <Repeat2 className="h-3.5 w-3.5" aria-hidden /> : <Plus className="h-3.5 w-3.5" aria-hidden />}
      {label}
    </Button>
  );
}
