"use client";

/** The punter's ticket: scanner picks they added, kept in this browser. The server re-checks every pick before using it. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Category, Market, Prediction } from "./types";

export interface TicketItem {
  prediction_id: number; fixture_id: number; market: Market; home: string; away: string; competition: string;
  kickoff_at: string; probability: number; category: Category; is_demo: boolean;
}

export const MAX_TICKET = 20;
const KEY = "f5m-ticket-v1";

export function itemFromPrediction(p: Prediction): TicketItem | null {
  if (!p.fixture) return null;
  return {
    prediction_id: p.id, fixture_id: p.fixture_id, market: p.market, home: p.fixture.home_team.name, away: p.fixture.away_team.name,
    competition: p.fixture.competition.name, kickoff_at: p.fixture.kickoff_at, probability: p.probability, category: p.category, is_demo: p.is_demo,
  };
}

interface Ctx {
  items: TicketItem[]; has: (predictionId: number) => boolean; hasFixture: (fixtureId: number) => boolean;
  toggle: (item: TicketItem) => void; remove: (predictionId: number) => void; replace: (oldId: number, item: TicketItem) => void; clear: () => void;
}
const TicketContext = createContext<Ctx | null>(null);

function load(): TicketItem[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((i) => typeof i?.prediction_id === "number").slice(0, MAX_TICKET) : [];
  } catch {
    return [];
  }
}

export function TicketProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<TicketItem[]>([]);
  const [ready, setReady] = useState(false);
  useEffect(() => { setItems(load()); setReady(true); }, []);
  useEffect(() => {
    if (!ready) return;
    try { window.localStorage.setItem(KEY, JSON.stringify(items)); } catch { /* private mode: the ticket just won't persist */ }
  }, [items, ready]);

  const toggle = useCallback((item: TicketItem) => setItems((cur) => {
    if (cur.some((i) => i.prediction_id === item.prediction_id)) return cur.filter((i) => i.prediction_id !== item.prediction_id);
    const others = cur.filter((i) => i.fixture_id !== item.fixture_id);      // one pick per game, like a normal accumulator
    return others.length >= MAX_TICKET ? others : [...others, item];
  }), []);
  const remove = useCallback((id: number) => setItems((cur) => cur.filter((i) => i.prediction_id !== id)), []);
  const replace = useCallback((oldId: number, item: TicketItem) => setItems((cur) => cur.map((i) => (i.prediction_id === oldId ? item : i))), []);
  const clear = useCallback(() => setItems([]), []);
  const value = useMemo<Ctx>(() => ({
    items, toggle, remove, replace, clear,
    has: (id) => items.some((i) => i.prediction_id === id),
    hasFixture: (id) => items.some((i) => i.fixture_id === id),
  }), [items, toggle, remove, replace, clear]);
  return <TicketContext.Provider value={value}>{children}</TicketContext.Provider>;
}

export function useTicket(): Ctx {
  const ctx = useContext(TicketContext);
  if (!ctx) throw new Error("useTicket must be used inside TicketProvider");
  return ctx;
}
