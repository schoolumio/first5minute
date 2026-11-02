"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
import { api, ApiError } from "@/lib/api";

const CARDS = [
  { value: "works", label: "Visa ending 4081", note: "Renewals succeed - use this to test a normal subscription." },
  { value: "declines", label: "Mastercard ending 0408", note: "First payment succeeds, every renewal is declined - use this to test retries, grace period and expiry." },
] as const;

function DemoCheckout() {
  const router = useRouter();
  const reference = useSearchParams().get("reference");
  const [card, setCard] = useState<"works" | "declines">("works");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pay = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/subscriptions/demo/complete", { method: "POST", body: { reference, card } });
      router.push(`/account?tab=billing&reference=${encodeURIComponent(reference ?? "")}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Demo payment failed");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <PageHeader title="Demo checkout" description="A simulated payment page for local testing." />
      <Alert tone="warn">DEMO ONLY - no real money moves and no real card is used. This page exists only when PAYMENT_PROVIDER=demo.</Alert>
      {!reference && <Alert tone="danger">Missing payment reference. Start from the pricing page.</Alert>}
      {error && <Alert tone="danger">{error}</Alert>}
      <Card>
        <CardHeader title="Choose a simulated card" />
        <CardBody className="space-y-3">
          {CARDS.map((c) => (
            <label key={c.value} className="flex cursor-pointer items-start gap-3 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3 text-sm has-[:checked]:border-brand-500">
              <input type="radio" name="card" className="mt-1" checked={card === c.value} onChange={() => setCard(c.value)} />
              <span><span className="font-semibold">{c.label}</span><br /><span className="text-muted">{c.note}</span></span>
            </label>
          ))}
          <Button className="w-full" loading={busy} disabled={!reference} onClick={pay}>Pay (demo)</Button>
        </CardBody>
      </Card>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={null}><DemoCheckout /></Suspense>;
}
