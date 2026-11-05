"use client";

import { useState } from "react";
import { ArrowLeftRight, CheckCircle2, Circle, Loader2, RotateCcw } from "lucide-react";
import { BookingCard, SelectionsList, SummaryStats } from "@/components/booking/results";
import { TicketBuilder, type TicketPickRef } from "@/components/booking/ticket-builder";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Tabs } from "@/components/ui/data";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import { cleanCode } from "@/lib/booking";
import { useApi } from "@/lib/hooks";
import type { Catalog, Conversion, ConverterBookmaker } from "@/lib/types";

type Phase = "form" | "working" | "results";
type Mode = "ticket" | "code";

const STEPS: Record<Mode, { title: string; hint: string }[]> = {
  code: [
    { title: "Checking the code and reading its selections", hint: "Validating the code and retrieving the original selections." },
    { title: "Matching fixtures and markets", hint: "Finding each game and the exact same bet at the other bookmaker." },
    { title: "Creating the new booking code", hint: "Asking the bookmaker for a real code." },
  ],
  ticket: [
    { title: "Preparing your ticket", hint: "Checking your picks are still available." },
    { title: "Matching games and markets at your bookmaker", hint: "Finding each game and the exact same bet there." },
    { title: "Creating your booking code", hint: "Asking the bookmaker for a real code." },
  ],
};

function Progress({ step, mode }: { step: number; mode: Mode }) {
  return (
    <Card>
      <CardBody>
        <ol className="space-y-4" aria-live="polite" aria-label="Conversion progress">
          {STEPS[mode].map((s, i) => {
            const state = i < step ? "done" : i === step ? "active" : "todo";
            return (
              <li key={s.title} className="flex items-start gap-3">
                {state === "done" ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-brand-400" aria-hidden />
                  : state === "active" ? <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-brand-400" aria-hidden />
                  : <Circle className="mt-0.5 h-5 w-5 shrink-0 text-border-strong" aria-hidden />}
                <div className="min-w-0">
                  <p className={state === "todo" ? "text-sm text-subtle" : "text-sm font-semibold"}>{s.title}</p>
                  {state === "active" && <p className="text-xs text-muted">{s.hint}</p>}
                </div>
              </li>
            );
          })}
        </ol>
      </CardBody>
    </Card>
  );
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return "Something went wrong. Please try again.";
}

export default function BookingCodeConverterPage() {
  const { data, loading, error } = useApi<{ enabled: boolean; bookmakers: ConverterBookmaker[] }>("/booking-converter/bookmakers");
  const [mode, setMode] = useState<Mode>("ticket");
  const catalog = useApi<Catalog>(mode === "ticket" && phase0(data) ? "/booking-converter/catalog" : null);
  const [code, setCode] = useState("");
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState("");
  const [phase, setPhase] = useState<Phase>("form");
  const [step, setStep] = useState(0);
  const [conv, setConv] = useState<Conversion | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [genBusy, setGenBusy] = useState(false);
  const [builderKey, setBuilderKey] = useState(0);

  const bookmakers = data?.bookmakers ?? [];
  const anyConnected = bookmakers.some((b) => b.can_decode) && bookmakers.some((b) => b.can_be_destination);
  const canSubmit = cleanCode(code).length >= 3 && source && destination && source !== destination;

  const reset = () => {
    setPhase("form"); setConv(null); setErr(null); setStep(0); setCode("");
    setBuilderKey((k) => k + 1);                 // clears the ticket
  };

  /** Shared pipeline: start (decode a code, or create a ticket) -> match -> generate when everything matched. */
  const run = async (start: () => Promise<Conversion>) => {
    setErr(null);
    setPhase("working");
    setStep(0);
    let latest: Conversion | null = null;
    try {
      latest = await start();
      setConv(latest);
      setStep(1);
      latest = await api<Conversion>(`/booking-converter/${latest.id}/match`, { method: "POST" });
      setConv(latest);
      // Everything matched: ask the destination for a real code (or prepare the manual slip). Otherwise the user decides first.
      if (latest.state === "matched" && latest.counts.matched === latest.counts.original) {
        if (latest.destination.can_generate) setStep(2);
        latest = await api<Conversion>(`/booking-converter/${latest.id}/generate`, { method: "POST", body: { proceed_with_partial: false } });
        setConv(latest);
      }
      setPhase("results");
    } catch (ex) {
      setErr(errorText(ex));
      setPhase(latest ? "results" : "form");   // keep showing what we have if the first step already worked
    }
  };

  const convert = (e: React.FormEvent) => {
    e.preventDefault();
    if (canSubmit) void run(() => api<Conversion>("/booking-converter/decode", { method: "POST", body: { code: cleanCode(code), source, destination } }));
  };
  const buildTicket = (dest: string, picks: TicketPickRef[]) =>
    void run(() => api<Conversion>("/booking-converter/ticket", { method: "POST", body: { destination: dest, picks } }));

  const generate = async (partial: boolean) => {
    if (!conv) return;
    setGenBusy(true);
    setErr(null);
    try {
      setConv(await api<Conversion>(`/booking-converter/${conv.id}/generate`, { method: "POST", body: { proceed_with_partial: partial } }));
    } catch (ex) {
      setErr(errorText(ex));
    } finally {
      setGenBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Convert Booking Code" description="Build a ticket and get a booking code for your bookmaker, or move an existing code between bookmakers. We never place bets: you copy the code and place it yourself." />
      {error && <Alert tone="danger" className="mb-4">{error.message}</Alert>}
      {loading && <Skeleton className="h-64" />}
      {data && !data.enabled && <Alert tone="warn" title="Temporarily unavailable">The converter is switched off right now. Please check back later.</Alert>}

      {data?.enabled && phase === "form" && (
        <Tabs<Mode> className="mb-4" value={mode} onChange={(m) => { setMode(m); setErr(null); }}
          options={[{ value: "ticket", label: "Build a ticket" }, { value: "code", label: "Convert a code" }]} />
      )}

      {data?.enabled && phase === "working" && <div className="mx-auto max-w-xl"><Progress step={step} mode={mode} /></div>}

      {data?.enabled && phase === "form" && mode === "ticket" && (
        catalog.loading || !catalog.data ? (catalog.error ? <Alert tone="danger">{catalog.error.message}</Alert> : <Skeleton className="h-64" />) : (
          <TicketBuilder key={builderKey} catalog={catalog.data} bookmakers={bookmakers} busy={false} error={err} onGenerate={buildTicket} />
        )
      )}

      {data?.enabled && phase === "form" && mode === "code" && (
        <div className="mx-auto max-w-xl space-y-4">
          {!anyConnected && <Alert tone="info" title="No bookmakers are connected yet">Booking codes can only be converted for bookmakers we have an official integration with. None is connected at the moment, so conversions are not available yet.</Alert>}
          {bookmakers.some((b) => b.is_demo) && <Alert tone="demo" title="Demo mode">Fictional bookmakers for testing. Codes to try: DEMOALL, DEMOPART, DEMOMARKET, DEMOGENFAIL, DEMOWOMEN.</Alert>}
          <Card>
            <CardBody>
              <form onSubmit={convert} className="space-y-4" noValidate>
                {err && <Alert tone="danger">{err}</Alert>}
                <Field label="Booking code" htmlFor="code" hint="Paste the code exactly as the bookmaker gave it.">
                  <Input id="code" inputMode="text" autoCapitalize="characters" autoCorrect="off" spellCheck={false} autoComplete="off" maxLength={64}
                    className="font-[family-name:var(--font-mono)] uppercase tracking-widest" placeholder="e.g. 8ZK4D2" value={code} onChange={(e) => setCode(e.target.value)} />
                </Field>
                <Field label="Convert from" htmlFor="source">
                  <Select id="source" value={source} onChange={(e) => setSource(e.target.value)}>
                    <option value="">Choose the bookmaker that made the code</option>
                    {bookmakers.map((b) => <option key={b.code} value={b.code} disabled={!b.can_decode}>{b.name}{b.can_decode ? "" : " - not connected yet"}</option>)}
                  </Select>
                </Field>
                <Field label="Convert to" htmlFor="destination" error={source && source === destination ? "Choose two different bookmakers." : null}>
                  <Select id="destination" value={destination} onChange={(e) => setDestination(e.target.value)}>
                    <option value="">Choose the bookmaker you want to use</option>
                    {bookmakers.map((b) => <option key={b.code} value={b.code} disabled={!b.can_be_destination}>{b.name}{b.can_be_destination ? "" : " - not connected yet"}</option>)}
                  </Select>
                </Field>
                <Button type="submit" size="lg" className="w-full" disabled={!canSubmit || !anyConnected}>
                  <ArrowLeftRight className="h-4 w-4" aria-hidden /> Convert
                </Button>
                <p className="text-xs text-subtle">18+. Odds change quickly: always check your slip on the bookmaker before you bet. We never place bets or hold your money.</p>
              </form>
            </CardBody>
          </Card>
        </div>
      )}

      {data?.enabled && phase === "results" && conv && (
        <div className="space-y-5">
          {err && <Alert tone="danger">{err}</Alert>}
          {conv.is_demo && <Alert tone="demo" title="Demo conversion">This used fictional demo bookmakers. Nothing here is real.</Alert>}
          {conv.deduplicated && <Alert tone="info">You converted this code a moment ago, so we are showing that result again.</Alert>}
          <SummaryStats conv={conv} />
          <BookingCard conv={conv} onGenerate={generate} busy={genBusy} />
          <SelectionsList conv={conv} />
          <p className="text-xs text-subtle">{conv.notice}</p>
          <Button type="button" variant="outline" onClick={reset} className="w-full sm:w-auto">
            <RotateCcw className="h-4 w-4" aria-hidden /> {mode === "ticket" ? "Build another ticket" : "Convert another code"}
          </Button>
        </div>
      )}
    </>
  );
}

function phase0(d: { enabled: boolean } | null): boolean {
  return Boolean(d?.enabled);
}
