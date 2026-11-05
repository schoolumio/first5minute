"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Radar, RotateCcw, Ticket, Trash2 } from "lucide-react";
import { BookingCard, SelectionsList, SummaryStats, Warnings } from "@/components/booking/results";
import { Progress, TICKET_STEPS } from "@/components/booking/progress";
import { PageHeader } from "@/components/layout/app-shell";
import { Badge, CategoryBadge, QualityIndicator } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { ProbabilityBar, ProbabilityValue } from "@/components/ui/data";
import { Alert, EmptyState, Skeleton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";
import { api } from "@/lib/api";
import { useConversionFlow } from "@/lib/conversion-flow";
import { kickoff, MARKET_LABEL } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { MAX_TICKET, useTicket, type TicketItem } from "@/lib/ticket";
import type { Conversion, ConverterBookmaker, TicketPreviewItem } from "@/lib/types";

function Leg({ item, info, onRemove }: { item: TicketItem; info?: TicketPreviewItem; onRemove: () => void }) {
  const a = info && info.probability !== undefined ? info : null;
  const prob = a?.probability ?? item.probability;
  const blocked = info && !info.available;
  return (
    <Card className={blocked ? "border-danger/40" : undefined}>
      <CardBody className="space-y-3 !p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-wide text-subtle">{item.competition}{item.is_demo && <Badge tone="demo" className="ml-2">Demo</Badge>}</p>
            <p className="break-words font-semibold">{item.home} <span className="font-normal text-muted">vs</span> {item.away}</p>
            <p className="text-xs text-muted">{kickoff(item.kickoff_at)}</p>
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${item.home} vs ${item.away}`} onClick={onRemove}><Trash2 className="h-4 w-4" aria-hidden /></Button>
        </div>
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-wide text-subtle">{MARKET_LABEL[item.market]}</p>
            <ProbabilityValue value={prob} className="text-2xl" />
          </div>
          <div className="flex flex-col items-end gap-1.5"><CategoryBadge category={a?.category ?? item.category} />{a?.data_quality && <QualityIndicator quality={a.data_quality} />}</div>
        </div>
        <ProbabilityBar value={prob} />
        {a && (
          <p className="text-xs text-muted">
            {a.fair_odds ? <>Fair odds <span className="tabular font-semibold text-fg">{a.fair_odds.toFixed(2)}</span> · </> : null}
            Confidence <span className="font-semibold capitalize text-fg">{a.confidence}</span> · Sample <span className="tabular font-semibold text-fg">{a.sample}</span> matches ·{" "}
            {a.calibration_status === "calibrated" ? "Calibrated" : "Uncalibrated"} estimate ({a.model})
          </p>
        )}
        {blocked && <Alert tone="danger">{info?.reason}</Alert>}
      </CardBody>
    </Card>
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
  const { conv, phase } = flow;

  const generate = () => {
    if (!usable.length || !bookie) return;
    void flow.run(() => api<Conversion>("/booking-converter/ticket", { method: "POST", body: { destination: bookie, prediction_ids: usable.map((i) => i.prediction_id) } }));
  };
  const startNew = () => { clear(); flow.reset(); setBookie(""); };

  return (
    <>
      <PageHeader title="My ticket" description="Games you picked from the scanner, with the model's analysis. Choose your bookmaker and we create the same ticket there and give you a booking code to copy." />

      {phase === "working" && <div className="mx-auto max-w-xl"><Progress step={flow.step} steps={TICKET_STEPS} /></div>}

      {phase === "form" && (
        !items.length ? (
          <Card><EmptyState icon={Ticket} title="Your ticket is empty">Open the Match scanner, read the analysis and press <b>Add to ticket</b> on the games you like.
            <div className="mt-3"><Link href="/scanner" className="inline-flex items-center gap-1 font-semibold text-brand-400 hover:underline"><Radar className="h-4 w-4" aria-hidden /> Go to the Match scanner</Link></div></EmptyState></Card>
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            {flow.err && <Alert tone="danger">{flow.err}</Alert>}
            {notice && <Alert tone="info">{notice}</Alert>}
            {books.data?.bookmakers.some((b) => b.is_demo) && <Alert tone="demo" title="Demo mode">Fictional games and bookmakers. Codes you get are demo codes and will not work on a real bookmaker.</Alert>}
            {unavailable > 0 && (
              <Alert tone="warn" title={`${unavailable} ${unavailable === 1 ? "pick" : "picks"} can't be used`}>
                They are marked below. Remove them to continue.
                <div className="mt-2"><Button type="button" size="sm" variant="outline" onClick={() => items.filter((i) => preview[i.prediction_id]?.available === false).forEach((i) => remove(i.prediction_id))}>Remove unavailable picks</Button></div>
              </Alert>
            )}
            <div className="flex items-center justify-between text-sm text-muted">
              <p>{items.length} {items.length === 1 ? "game" : "games"} (one pick per game, up to {MAX_TICKET}){checking && " · checking the latest analysis…"}</p>
              <button type="button" onClick={clear} className="cursor-pointer text-xs hover:text-fg">Clear ticket</button>
            </div>
            <div className="space-y-3">{items.map((i) => <Leg key={i.prediction_id} item={i} info={preview[i.prediction_id]} onRemove={() => remove(i.prediction_id)} />)}</div>

            <Card className="border-brand-500/40">
              <CardBody className="space-y-3">
                <p className="text-sm font-semibold">Where will you place it?</p>
                {books.loading ? <Skeleton className="h-10" /> : (
                  <Select aria-label="Your bookmaker" value={bookie} onChange={(e) => setBookie(e.target.value)}>
                    <option value="">Choose your bookmaker</option>
                    {bookmakers.map((b) => <option key={b.code} value={b.code} disabled={!b.can_be_destination}>{b.name}{b.can_be_destination ? (b.can_generate ? "" : " (slip only, no code)") : " - not connected yet"}</option>)}
                  </Select>
                )}
                {!books.loading && !bookmakers.some((b) => b.can_be_destination) && <Alert tone="info" title="No bookmaker is connected yet">Booking codes need an official integration with the bookmaker. None is connected at the moment.</Alert>}
                {dest && !dest.can_generate && <p className="text-xs text-warn">{dest.name} can&apos;t create codes through First5Minute, so you&apos;ll get your slip to copy instead.</p>}
                <Button type="button" size="lg" className="w-full" disabled={!usable.length || !bookie || unavailable > 0 || checking} onClick={generate}>
                  Generate booking code
                </Button>
                <p className="text-xs text-subtle">18+. Probabilities are model estimates, not guarantees, and the five-minute markets are priced and settled differently by each bookmaker. You copy the code and place the bet yourself; we never place bets or hold money.</p>
              </CardBody>
            </Card>
          </div>
        )
      )}

      {phase === "results" && conv && (
        <div className="space-y-5">
          {flow.err && <Alert tone="danger">{flow.err}</Alert>}
          {conv.is_demo && <Alert tone="demo" title="Demo ticket">Fictional games and bookmakers. Nothing here is real.</Alert>}
          <SummaryStats conv={conv} />
          <BookingCard conv={conv} onGenerate={flow.generate} busy={flow.genBusy} />
          <Warnings conv={conv} />
          <SelectionsList conv={conv} />
          <p className="text-xs text-subtle">{conv.notice}</p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button type="button" variant="outline" onClick={() => flow.reset()}><RotateCcw className="h-4 w-4" aria-hidden /> Edit my ticket</Button>
            <Button type="button" variant="ghost" onClick={startNew}>Start a new ticket</Button>
          </div>
        </div>
      )}
    </>
  );
}
