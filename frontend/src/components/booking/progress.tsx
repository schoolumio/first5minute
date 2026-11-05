"use client";

import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import { Card, CardBody } from "@/components/ui/card";

export const CODE_STEPS = [
  { title: "Checking the code and reading its selections", hint: "Validating the code and retrieving the original selections." },
  { title: "Matching fixtures and markets", hint: "Finding each game and the exact same bet at the other bookmaker." },
  { title: "Creating the new booking code", hint: "Asking the bookmaker for a real code." },
];
export const TICKET_STEPS = [
  { title: "Checking your picks", hint: "Making sure every game is still open and the analysis is current." },
  { title: "Matching games and markets at your bookmaker", hint: "Finding each game and the exact first-5-minutes market there." },
  { title: "Creating your booking code", hint: "Asking the bookmaker for a real code." },
];

export function Progress({ step, steps }: { step: number; steps: { title: string; hint: string }[] }) {
  return (
    <Card>
      <CardBody>
        <ol className="space-y-4" aria-live="polite" aria-label="Conversion progress">
          {steps.map((s, i) => {
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
