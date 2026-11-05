"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Radar, RotateCcw, Ticket } from "lucide-react";
import { CopyButton } from "@/components/booking/results";
import { Progress, TICKET_STEPS } from "@/components/booking/progress";
import { PageHeader } from "@/components/layout/app-shell";
import { BookieTiles, SlipLeg, SlipResultLeg, Stepper } from "@/components/ticket/slip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Alert, EmptyState, Skeleton } from "@/components/ui/feedback";
import { api } from "@/lib/api";
import { ticketAsText } from "@/lib/booking";
import { useConversionFlow } from "@/lib/conversion-flow";
import { useApi } from "@/lib/hooks";
import { MAX_TICKET, useTicket } from "@/lib/ticket";
import type { Conversion, ConverterBookmaker, TicketPreviewItem } from "@/lib/types";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="flex items-baseline justify-between gap-3 text-sm"><dt className="text-muted">{label}</dt><dd className="tabular text-right font-semibold">{value}</dd></div>;
}

function HowTo({ bookie }: { bookie: string }) {
  return (
    <ol className="space-y-1.5 text-xs text-muted">
      {[`Open ${bookie} (app or website).`, "Find the betslip and choose “Booking code” or “Load code”.", "Paste the code and check every game and price.", "Set your own stake and place the bet yourself."].map((t, i) => (
        <li key={t} className="flex gap-2"><span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-surface-3 text-[10px] font-bold text-fg">{i + 1}</span>{t}</li>
      ))}
    </ol>
  );
}

export default function TicketPage() {
  const { items, remove, replace, clear } = useTicket();
  const books = useApi<{ enabled: boolean; bookmakers: ConverterBookmaker[] }>("/booking-converter/bookmakers");
  const flow = useConversionFlow();
  const [preview, setPreview] = useState<Record<number, TicketPreviewItem>>({});
  const [checking, setChecking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [bookie, setBookie] = useState("");
  const swapped = useRef(false);

  const ids = useMemo(() => items.map((i) => i.prediction_id), [items]);
  const key = ids.join(",");
  useEffect(() => {
    if (!ids.length) { setPreview({}); return; }
    let alive = true;
    setChecking(true);
    api<{ items: TicketPreviewItem[] }>("/booking-converter/ticket/preview", { method: "POST", body: { prediction_ids: ids } })
      .then(async (res) => {
        if (!alive) return;
        // the model re-ran for some matches: show the updated estimate (and say so) instead of using a stale one
        const stale = res.items.filter((i) => !i.available && i.replaced_by);
        if (stale.length && !swapped.current) {
          swapped.current = true;
          const fresh = await api<{ items: TicketPreviewItem[] }>("/booking-converter/ticket/preview", { method: "POST", body: { prediction_ids: stale.map((s) => s.replaced_by as number) } });
          const lines: string[] = [];
          for (const s of stale) {
            const f = fresh.items.find((x) => x.prediction_id === s.replaced_by);
            const old = items.find((i) => i.prediction_id === s.prediction_id);
            if (f && f.available && f.fixture && f.probability !== undefined && old) {
              replace(s.prediction_id, { prediction_id: f.prediction_id, fixture_id: f.fixture_id!, market: f.market!, home: f.fixture.home_team, away: f.fixture.away_team,
                competition: f.fixture.competition, kickoff_at: f.fixture.kickoff_at, probability: f.probability, category: f.category!, is_demo: !!f.is_demo });
              lines.push(`${old.home} vs ${old.away}: ${(old.probability * 100).toFixed(1)}% → ${(f.probability * 100).toFixed(1)}%`);
            }
          }
          if (lines.length) setNotice(`The model re-ran, so we updated these picks to the latest estimate: ${lines.join("; ")}.`);
          return;
        }
        swapped.current = false;
        setPreview(Object.fromEntries(res.items.map((i) => [i.prediction_id, i])));
      })
      .catch(() => alive && setPreview({}))
      .finally(() => alive && setChecking(false));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const bookmakers = books.data?.bookmakers ?? [];
  const usable = items.filter((i) => preview[i.prediction_id]?.available !== false);
  const unavailable = items.length - usable.length;
  const dest = bookmakers.find((b) => b.code === bookie);
  const allWin = items.length > 1 ? items.reduce((p, i) => p * (preview[i.prediction_id]?.probability ?? i.probability), 1) : null;
  const { conv, phase } = flow;
  const b = conv?.booking;
  const bookieName = conv?.destination.name ?? dest?.name ?? "your bookmaker";

  const ticketText = useMemo(() => ticketAsText(items, { preview }), [items, preview]);

  const generate = () => {
    if (!usable.length || !bookie) return;
    void flow.run(() => api<Conversion>("/booking-converter/ticket", { method: "POST", body: { destination: bookie, prediction_ids: usable.map((i) => i.prediction_id) } }));
  };
  const startNew = () => { clear(); flow.reset(); setBookie(""); };
  const empty = !items.length && phase === "form";

  return (
    <>
      <PageHeader eyebrow="Betslip tools" title="My ticket" description="The games you picked from the scanner. Choose where you'll bet and we build the same ticket there and give you its booking code." />

      {empty ? (
        <Card><EmptyState icon={Ticket} title="Your ticket is empty">Open the Match scanner, read the analysis and tap a pick to add it here.
          <div className="mt-3"><Link href="/scanner" className="inline-flex items-center gap-1 font-semibold text-brand-400 hover:underline"><Radar className="h-4 w-4" aria-hidden /> Go to the Match scanner</Link></div></EmptyState></Card>
      ) : (
        <>
          <Stepper step={phase === "results" ? 3 : 2} />
          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
            <section aria-label="Games on your ticket" className="space-y-3">
              {phase === "form" && notice && <Alert tone="info">{notice}</Alert>}
              {phase === "form" && unavailable > 0 && (
                <Alert tone="warn" title={`${unavailable} ${unavailable === 1 ? "pick" : "picks"} can't be used`}>
                  They are marked below. Remove them to continue.
                  <div className="mt-2"><Button type="button" size="sm" variant="outline" onClick={() => items.filter((i) => preview[i.prediction_id]?.available === false).forEach((i) => remove(i.prediction_id))}>Remove unavailable picks</Button></div>
                </Alert>
              )}
              {phase === "form" && (
                <div className="flex items-center justify-between text-xs text-muted">
                  <p>{items.length} {items.length === 1 ? "game" : "games"} · one pick per game · up to {MAX_TICKET}{checking && " · checking the latest analysis…"}</p>
                  <button type="button" onClick={clear} className="cursor-pointer hover:text-fg">Clear all</button>
                </div>
              )}
              {phase === "results" && conv
                ? conv.selections.map((s) => <SlipResultLeg key={s.index} s={s} bookie={conv.destination.name} />)
                : items.map((i) => <SlipLeg key={i.prediction_id} item={i} info={preview[i.prediction_id]} onRemove={() => remove(i.prediction_id)} />)}
            </section>

            <aside className={`space-y-4 lg:sticky lg:top-20 ${phase === "results" ? "order-first lg:order-none" : ""}`} aria-label="Booking code">
              <Card className="overflow-hidden border-brand-500/40">
                <div className="border-b border-border bg-gradient-to-r from-brand-900/60 to-transparent px-5 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-widest text-brand-400">Booking code</p>
                  <p className="text-sm font-semibold">{phase === "results" && b?.status === "generated" ? `${bookieName} ticket ready` : "Build your ticket"}</p>
                </div>
                <CardBody className="space-y-4">
                  {phase === "working" && <Progress step={flow.step} steps={TICKET_STEPS} />}

                  {phase === "form" && (
                    <>
                      {flow.err && <Alert tone="danger">{flow.err}</Alert>}
                      {books.data?.bookmakers.some((x) => x.is_demo) && <Alert tone="demo" title="Demo mode">Fictional games and bookmakers. You'll get a demo code, which won't work anywhere real.</Alert>}
                      <dl className="space-y-1.5">
                        <Row label="Games" value={items.length} />
                        {allWin !== null && <Row label="Chance all win (model)" value={`${(allWin * 100).toFixed(1)}%`} />}
                      </dl>
                      {allWin !== null && <p className="-mt-2 text-[11px] text-subtle">Assumes the games are independent. A model estimate, not a promise.</p>}
                      <div className="space-y-2">
                        <p className="text-sm font-semibold">Where will you place it?</p>
                        {books.loading ? <Skeleton className="h-32" /> : <BookieTiles bookmakers={bookmakers} value={bookie} onChange={setBookie} />}
                        {!books.loading && !bookmakers.some((x) => x.can_be_destination) && <Alert tone="info" title="No bookmaker is connected yet">Booking codes need an official integration with the bookmaker. None is connected at the moment.</Alert>}
                        {dest && !dest.can_generate && <p className="text-xs text-warn">{dest.name} can&apos;t create booking codes through First5Minute, so you&apos;ll get your slip to copy.</p>}
                      </div>
                      <Button type="button" size="lg" className="w-full" disabled={!usable.length || !bookie || unavailable > 0 || checking} onClick={generate}>
                        Generate booking code
                      </Button>
                      <p className="text-[11px] leading-relaxed text-subtle">18+. You copy the code and place the bet yourself. We never place bets or hold money. Bookmakers price and settle five-minute markets differently.</p>
                      <div className="space-y-2 border-t border-border pt-3">
                        <p className="text-xs text-muted">Bookmaker not connected, or you just want the list? Copy your ticket as text and rebuild it on any bookmaker yourself.</p>
                        <CopyButton text={ticketText} label="Copy ticket as text" variant="outline" />
                      </div>
                    </>
                  )}

                  {phase === "results" && conv && (
                    <>
                      {flow.err && <Alert tone="danger">{flow.err}</Alert>}
                      {b?.status === "generated" && b.code && (
                        <>
                          {b.is_demo && <Alert tone="demo" title="Demo code">Not a real {bookieName} code. It came from the local demo simulator.</Alert>}
                          <div className="rounded-[var(--radius-md)] border border-brand-500/40 bg-surface-2 px-4 py-5 text-center">
                            <p className="mb-1 flex items-center justify-center gap-1.5 text-xs font-semibold text-brand-400"><CheckCircle2 className="h-4 w-4" aria-hidden />Your {bookieName} booking code</p>
                            <p className="select-all break-all font-[family-name:var(--font-mono)] text-2xl font-bold tracking-[0.1em] sm:text-[26px]" aria-label="New booking code">{b.code}</p>
                          </div>
                          <CopyButton text={b.code} label="Copy booking code" />
                          <dl className="space-y-1.5 border-t border-border pt-3">
                            <Row label="Games on the code" value={`${conv.counts.matched} of ${conv.counts.original}`} />
                            <Row label={`Combined odds at ${bookieName}`} value={conv.totals.destination_odds ?? "-"} />
                          </dl>
                          <div className="border-t border-border pt-3"><p className="mb-2 text-xs font-semibold">Now place it yourself</p><HowTo bookie={bookieName} /></div>
                        </>
                      )}
                      {b?.status === "manual" && (
                        <>
                          <Alert tone="info" title={`${bookieName} can't create codes here`}>{b.message}</Alert>
                          {conv.betslip_text && <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-[var(--radius-md)] border border-border bg-surface-2 p-3 text-xs">{conv.betslip_text}</pre>}
                          {conv.betslip_text && <CopyButton text={conv.betslip_text} label="Copy slip" variant="outline" />}
                        </>
                      )}
                      {b?.status === "failed" && (
                        <>
                          <Alert tone="danger" title="No booking code was created">{b.message ?? `${bookieName} did not return a code.`} Nothing has been placed.</Alert>
                          <Button type="button" onClick={() => flow.generate(true)} loading={flow.genBusy} className="w-full">Try again</Button>
                        </>
                      )}
                      {!b && conv.counts.matched === 0 && <Alert tone="danger" title={`None of these games could be added at ${bookieName}`}>See the reason on each game. Try another bookmaker.</Alert>}
                      {!b && conv.needs_decision && (
                        <>
                          <Alert tone="warn" title={`${conv.counts.matched} of ${conv.counts.original} games can be added at ${bookieName}`}>
                            The others are marked on the left with the reason. A code with fewer games is a different bet, so we only make it if you say so.
                          </Alert>
                          <Button type="button" className="w-full" loading={flow.genBusy} onClick={() => flow.generate(true)}>Create code with {conv.counts.matched} {conv.counts.matched === 1 ? "game" : "games"}</Button>
                        </>
                      )}
                      <div className="flex flex-col gap-2 border-t border-border pt-3">
                        <Button type="button" variant="outline" onClick={() => flow.reset()}><RotateCcw className="h-4 w-4" aria-hidden /> {b?.status === "generated" ? "Edit ticket / try another bookmaker" : "Choose another bookmaker"}</Button>
                        <Button type="button" variant="ghost" onClick={startNew}>Start a new ticket</Button>
                      </div>
                    </>
                  )}
                </CardBody>
              </Card>

              {phase === "results" && conv && (
                <div className="space-y-2">
                  {conv.warnings.map((w) => <p key={w} className="flex gap-2 rounded-[var(--radius-md)] border border-warn/30 bg-warn/5 px-3 py-2 text-xs text-fg/80"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" aria-hidden />{w}</p>)}
                  <p className="text-[11px] text-subtle">{conv.notice}</p>
                  {conv.is_demo && <Badge tone="demo">Demo data</Badge>}
                </div>
              )}
            </aside>
          </div>
        </>
      )}
    </>
  );
}
