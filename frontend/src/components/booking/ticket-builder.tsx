"use client";

import { useMemo, useState } from "react";
import { ChevronDown, Search, Ticket, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Alert, EmptyState } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { cn } from "@/lib/cn";
import { kickoff } from "@/lib/format";
import type { Catalog, CatalogEvent, ConverterBookmaker } from "@/lib/types";

export type TicketPickRef = { event_id: string; pick_key: string };

function pickLabel(e: CatalogEvent, key: string): string {
  for (const m of e.markets) {
    const p = m.picks.find((x) => x.key === key);
    if (p) return `${m.label}: ${p.label}`;
  }
  return key;
}

function PickButton({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected}
      className={cn("min-h-11 flex-1 cursor-pointer rounded-[var(--radius-md)] border px-2 py-2 text-sm font-semibold transition-colors",
        selected ? "border-brand-500 bg-brand-500 text-[#06110a]" : "border-border-strong bg-surface-2 text-fg hover:border-brand-500/60")}>
      {label}
    </button>
  );
}

function EventCard({ e, selected, onPick }: { e: CatalogEvent; selected: string | undefined; onPick: (key: string) => void }) {
  const [more, setMore] = useState(false);
  const main = e.markets[0];
  const rest = e.markets.slice(1);
  const hiddenSelection = selected && !main.picks.some((p) => p.key === selected);
  return (
    <Card className={cn("p-4", selected && "border-brand-500/50")}>
      <p className="break-words font-semibold">{e.home_team} vs {e.away_team}</p>
      <p className="mb-3 text-xs text-subtle">{[e.competition, kickoff(e.start_time)].filter(Boolean).join(" · ")}</p>
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">{main.label}</p>
      <div className="flex gap-2">
        {main.picks.map((p) => <PickButton key={p.key} label={p.label} selected={selected === p.key} onClick={() => onPick(p.key)} />)}
      </div>
      <button type="button" onClick={() => setMore(!more)} aria-expanded={more}
        className="mt-3 flex min-h-9 cursor-pointer items-center gap-1 text-xs font-semibold text-brand-400 hover:underline">
        <ChevronDown className={cn("h-4 w-4 transition-transform", more && "rotate-180")} aria-hidden />
        {more ? "Fewer markets" : "More markets"}
        {hiddenSelection && !more && <span className="ml-1 rounded-full bg-brand-500/15 px-2 py-0.5 text-brand-400">{pickLabel(e, selected!)}</span>}
      </button>
      {more && (
        <div className="mt-2 space-y-3">
          {rest.map((m) => (
            <div key={m.key}>
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">{m.label}</p>
              <div className="flex gap-2">{m.picks.map((p) => <PickButton key={p.key} label={p.label} selected={selected === p.key} onClick={() => onPick(p.key)} />)}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function TicketBuilder({ catalog, bookmakers, busy, error, onGenerate }: {
  catalog: Catalog; bookmakers: ConverterBookmaker[]; busy: boolean; error: string | null;
  onGenerate: (destination: string, picks: TicketPickRef[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [bookie, setBookie] = useState("");
  const events = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? catalog.events.filter((e) => `${e.home_team} ${e.away_team} ${e.competition ?? ""}`.toLowerCase().includes(q)) : catalog.events;
  }, [catalog.events, query]);
  const byId = useMemo(() => Object.fromEntries(catalog.events.map((e) => [e.id, e])), [catalog.events]);
  const refs = Object.entries(picked).map(([event_id, pick_key]) => ({ event_id, pick_key }));
  const dest = bookmakers.find((b) => b.code === bookie);
  const toggle = (id: string, key: string) => setPicked((p) => { const n = { ...p }; if (n[id] === key) delete n[id]; else n[id] = key; return n; });

  return (
    <div className="space-y-4 pb-4">
      <p className="text-sm text-muted">Pick the games you want, choose your bookmaker and press <b>Generate code</b>. We build the same ticket there and give you a booking code to copy.</p>
      {catalog.is_demo && <Alert tone="demo" title="Demo games">Fictional fixtures for testing. Codes are demo codes and will not work on a real bookmaker.</Alert>}
      {catalog.message && !catalog.is_demo && <Alert tone="info">{catalog.message}</Alert>}
      {error && <Alert tone="danger">{error}</Alert>}
      {catalog.events.length > 0 && (
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-subtle" aria-hidden />
          <Input aria-label="Search games" className="pl-9" placeholder="Search team or competition" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      )}
      {!events.length ? <Card><EmptyState icon={Ticket} title="No games to pick from">{catalog.events.length ? "No games match your search." : "Games appear here once a football data source is connected."}</EmptyState></Card> : (
        <div className="space-y-3">{events.map((e) => <EventCard key={e.id} e={e} selected={picked[e.id]} onPick={(k) => toggle(e.id, k)} />)}</div>
      )}

      <div className="sticky bottom-3 z-20 rounded-[var(--radius-lg)] border border-brand-500/40 bg-surface p-4 shadow-[var(--shadow-card)]">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold"><Ticket className="mr-1.5 inline h-4 w-4 text-brand-400" aria-hidden />Your ticket: {refs.length} {refs.length === 1 ? "game" : "games"}</p>
          {refs.length > 0 && <button type="button" onClick={() => setPicked({})} className="flex min-h-9 cursor-pointer items-center gap-1 text-xs text-muted hover:text-fg"><X className="h-3.5 w-3.5" aria-hidden />Clear</button>}
        </div>
        {refs.length > 0 && (
          <ul className="mt-2 max-h-28 space-y-1 overflow-y-auto text-xs text-muted">
            {refs.map((r) => <li key={r.event_id} className="break-words"><span className="text-fg">{byId[r.event_id].home_team} vs {byId[r.event_id].away_team}</span> · {pickLabel(byId[r.event_id], r.pick_key)}</li>)}
          </ul>
        )}
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <Select aria-label="Your bookmaker" value={bookie} onChange={(e) => setBookie(e.target.value)} className="sm:flex-1">
            <option value="">Choose your bookmaker</option>
            {bookmakers.map((b) => <option key={b.code} value={b.code} disabled={!b.can_be_destination}>{b.name}{b.can_be_destination ? (b.can_generate ? "" : " (slip only, no code)") : " - not connected yet"}</option>)}
          </Select>
          <Button type="button" size="lg" className="sm:w-auto" loading={busy} disabled={!refs.length || !bookie || refs.length > catalog.max_picks}
            onClick={() => onGenerate(bookie, refs)}>
            Generate code
          </Button>
        </div>
        {dest && !dest.can_generate && <p className="mt-2 text-xs text-warn">{dest.name} can&apos;t create codes through First5Minute, so you&apos;ll get your slip to copy instead.</p>}
        {refs.length > catalog.max_picks && <p className="mt-2 text-xs text-danger">At most {catalog.max_picks} games per ticket.</p>}
        <p className="mt-2 text-xs text-subtle">18+. One pick per game. Prices are shown from your bookmaker after we match the ticket. Check them before you bet.</p>
      </div>
    </div>
  );
}
