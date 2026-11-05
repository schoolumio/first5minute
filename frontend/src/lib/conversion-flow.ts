"use client";

import { useState } from "react";
import { api, ApiError } from "./api";
import type { Conversion } from "./types";

export type Phase = "form" | "working" | "results";

function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
}

/** decode/ticket -> match -> generate (automatically when everything matched; otherwise the user decides). Shared by both pages. */
export function useConversionFlow() {
  const [phase, setPhase] = useState<Phase>("form");
  const [step, setStep] = useState(0);
  const [conv, setConv] = useState<Conversion | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [genBusy, setGenBusy] = useState(false);

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

  const reset = () => { setPhase("form"); setConv(null); setErr(null); setStep(0); };
  return { phase, step, conv, err, genBusy, run, generate, reset, setErr };
}
