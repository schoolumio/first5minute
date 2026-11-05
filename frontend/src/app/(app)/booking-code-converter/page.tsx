"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeftRight, RotateCcw, Ticket } from "lucide-react";
import { BookingCard, SelectionsList, SummaryStats, Warnings } from "@/components/booking/results";
import { CODE_STEPS, Progress } from "@/components/booking/progress";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { api } from "@/lib/api";
import { cleanCode } from "@/lib/booking";
import { useConversionFlow } from "@/lib/conversion-flow";
import { useApi } from "@/lib/hooks";
import type { Conversion, ConverterBookmaker } from "@/lib/types";

export default function BookingCodeConverterPage() {
  const { data, loading, error } = useApi<{ enabled: boolean; bookmakers: ConverterBookmaker[] }>("/booking-converter/bookmakers");
  const flow = useConversionFlow();
  const [code, setCode] = useState("");
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState("");

  const bookmakers = data?.bookmakers ?? [];
  const anyConnected = bookmakers.some((b) => b.can_decode) && bookmakers.some((b) => b.can_be_destination);
  const canSubmit = cleanCode(code).length >= 3 && source && destination && source !== destination;

  const convert = (e: React.FormEvent) => {
    e.preventDefault();
    if (canSubmit) void flow.run(() => api<Conversion>("/booking-converter/decode", { method: "POST", body: { code: cleanCode(code), source, destination } }));
  };
  const again = () => { flow.reset(); setCode(""); };
  const { conv, phase } = flow;

  return (
    <>
      <PageHeader title="Convert Booking Code" description="Move an existing booking code from one bookmaker to another. We never place bets: you copy the new code and place it yourself." />
      <Alert tone="info" className="mb-4">
        Want a ticket from First5Minute&apos;s own analysis? Pick games in the <Link href="/scanner" className="font-semibold underline">Match scanner</Link> and add them to your <Link href="/ticket" className="font-semibold underline"><Ticket className="inline h-3.5 w-3.5" aria-hidden /> ticket</Link>.
      </Alert>
      {error && <Alert tone="danger" className="mb-4">{error.message}</Alert>}
      {loading && <Skeleton className="h-64" />}
      {data && !data.enabled && <Alert tone="warn" title="Temporarily unavailable">The converter is switched off right now. Please check back later.</Alert>}

      {data?.enabled && phase === "working" && <div className="mx-auto max-w-xl"><Progress step={flow.step} steps={CODE_STEPS} /></div>}

      {data?.enabled && phase === "form" && (
        <div className="mx-auto max-w-xl space-y-4">
          {!anyConnected && <Alert tone="info" title="No bookmakers are connected yet">Booking codes can only be converted for bookmakers we have an official integration with. None is connected at the moment, so conversions are not available yet.</Alert>}
          {bookmakers.some((b) => b.is_demo) && <Alert tone="demo" title="Demo mode">Fictional bookmakers for testing. Codes to try: DEMOALL, DEMOPART, DEMOMARKET, DEMOGENFAIL, DEMOWOMEN.</Alert>}
          <Card>
            <CardBody>
              <form onSubmit={convert} className="space-y-4" noValidate>
                {flow.err && <Alert tone="danger">{flow.err}</Alert>}
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
          {flow.err && <Alert tone="danger">{flow.err}</Alert>}
          {conv.is_demo && <Alert tone="demo" title="Demo conversion">This used fictional demo bookmakers. Nothing here is real.</Alert>}
          {conv.deduplicated && <Alert tone="info">You converted this code a moment ago, so we are showing that result again.</Alert>}
          <SummaryStats conv={conv} />
          <BookingCard conv={conv} onGenerate={flow.generate} busy={flow.genBusy} />
          <Warnings conv={conv} />
          <SelectionsList conv={conv} />
          <p className="text-xs text-subtle">{conv.notice}</p>
          <Button type="button" variant="outline" onClick={again} className="w-full sm:w-auto"><RotateCcw className="h-4 w-4" aria-hidden /> Convert another code</Button>
        </div>
      )}
    </>
  );
}
