"use client";

import { useState } from "react";
import { ArrowLeftRight, CheckCircle2, Circle, Loader2, RotateCcw } from "lucide-react";
import { BookingCard, SelectionsList, SummaryStats } from "@/components/booking/results";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import { cleanCode } from "@/lib/booking";
import { useApi } from "@/lib/hooks";
import type { Conversion, ConverterBookmaker } from "@/lib/types";

type Phase = "form" | "working" | "results";

const STEPS = [
  { title: "Checking the code and reading its selections", hint: "Validating the code and retrieving the original selections." },
  { title: "Matching fixtures and markets", hint: "Finding each game and the exact same bet at the other bookmaker." },
  { title: "Creating the new booking code", hint: "Asking the bookmaker for a real code." },
];

function Progress({ step }: { step: number }) {
  return (
    <Card>
      <CardBody>
        <ol className="space-y-4" aria-live="polite" aria-label="Conversion progress">
          {STEPS.map((s, i) => {
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
  const [code, setCode] = useState("");
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState("");
  const [phase, setPhase] = useState<Phase>("form");
  const [step, setStep] = useState(0);
  const [conv, setConv] = useState<Conversion | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [genBusy, setGenBusy] = useState(false);

  const bookmakers = data?.bookmakers ?? [];
  const anyConnected = bookmakers.some((b) => b.can_decode) && bookmakers.some((b) => b.can_be_destination);
  const canSubmit = cleanCode(code).length >= 3 && source && destination && source !== destination;

  const reset = () => { setPhase("form"); setConv(null); setErr(null); setStep(0); setCode(""); };

  const convert = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setErr(null);
    setPhase("working");
    setStep(0);
    let latest: Conversion | null = null;
    try {
      latest = await api<Conversion>("/booking-converter/decode", { method: "POST", body: { code: cleanCode(code), source, destination } });
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
      setPhase(latest ? "results" : "form");   // keep showing the original selections if decoding already worked
    }
  };

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
      <PageHeader title="Convert Booking Code" description="Move your slip from one bookmaker to another. We never place bets: we only recreate the same selections and, where the bookmaker allows, get you a real booking code." />
      {error && <Alert tone="danger" className="mb-4">{error.message}</Alert>}
      {loading && <Skeleton className="h-64" />}
      {data && !data.enabled && <Alert tone="warn" title="Temporarily unavailable">The converter is switched off right now. Please check back later.</Alert>}

      {data?.enabled && phase !== "results" && (
        <div className="mx-auto max-w-xl space-y-4">
          {data.bookmakers.some((b) => b.is_demo) && <Alert tone="demo" title="Demo mode">Fictional bookmakers for testing. Codes to try: DEMOALL, DEMOPART, DEMOMARKET, DEMOGENFAIL, DEMOWOMEN.</Alert>}
          {!anyConnected && <Alert tone="info" title="No bookmakers are connected yet">Booking codes can only be converted for bookmakers we have an official integration with. None is connected at the moment, so conversions are not available yet.</Alert>}
          {phase === "working" ? <Progress step={step} /> : (
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
          )}
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
          <Button type="button" variant="outline" onClick={reset} className="w-full sm:w-auto"><RotateCcw className="h-4 w-4" aria-hidden /> Convert another code</Button>
        </div>
      )}
    </>
  );
}
