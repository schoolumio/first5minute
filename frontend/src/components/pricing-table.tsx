"use client";

import { Check, Minus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, Skeleton } from "@/components/ui/feedback";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Plan } from "@/lib/types";

const FEATURE_ORDER: [string, string][] = [
  ["scanner_full", "Full daily match scanner"],
  ["historical_analysis", "Last 10/20 form, head-to-head & timing charts"],
  ["advanced_filters", "Advanced filters (sample, quality, team, country)"],
  ["odds_comparison", "Odds comparison & value sorting"],
  ["notifications", "Qualified-match notifications"],
  ["performance_analytics", "Calibration & walk-forward analytics"],
  ["advanced_reports", "Advanced reports"],
  ["api_access", "REST API access"],
];

export function PricingTable() {
  const { data, loading } = useApi<{ plans: Plan[]; payments_enabled: boolean }>("/plans");
  const { user } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = user?.entitlements?.plan;

  const choose = async (plan: Plan) => {
    setError(null);
    if (!user) return router.push(`/register?plan=${plan.code}`);
    if (plan.price_minor === 0) return router.push("/dashboard");
    setBusy(plan.code);
    try {
      const res = await api<{ authorization_url: string }>("/subscriptions/checkout", { method: "POST", body: { plan_code: plan.code } });
      window.location.href = res.authorization_url;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Checkout failed");
    } finally {
      setBusy(null);
    }
  };

  if (loading || !data)
    return (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-96" />)}
      </div>
    );

  return (
    <div>
      {error && <Alert tone="warn" className="mb-4">{error}</Alert>}
      {!data.payments_enabled && (
        <Alert tone="info" className="mb-4">
          Online payments are not enabled in this environment. Paid plans can be activated once a payment provider is configured.
        </Alert>
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {data.plans.map((p) => {
          const featured = p.code === "pro";
          const limit = p.features.scanner_daily_limit;
          return (
            <div key={p.code} className={cn("panel relative flex flex-col rounded-[var(--radius-xl)] p-6",
              featured && "border-brand-500/60 shadow-[var(--shadow-glow)]")}>
              {featured && <Badge tone="brand" className="absolute -top-2.5 left-6">Most popular</Badge>}
              <p className="font-[family-name:var(--font-mono)] text-[11px] font-semibold uppercase tracking-[0.2em] text-muted">{p.name}</p>
              <p className="numeral mt-3 text-[40px] leading-none">
                {p.price_minor === 0 ? "Free" : money(p.price, p.currency)}
                {p.price_minor > 0 && <span className="font-[family-name:var(--font-sans)] text-sm font-medium text-muted"> /{p.interval}</span>}
              </p>
              <p className="mt-2 min-h-10 text-sm text-muted">{p.description}</p>
              <ul className="mt-5 flex-1 space-y-2.5 text-sm">
                <li className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" />
                  {typeof limit === "number" ? `Top ${limit} scanner matches per day` : "Unlimited scanner results"}</li>
                {FEATURE_ORDER.map(([key, label]) => {
                  const on = Boolean(p.features[key]);
                  return (
                    <li key={key} className={cn("flex gap-2", !on && "text-subtle")}>
                      {on ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" /> : <Minus className="mt-0.5 h-4 w-4 shrink-0" />}
                      {label}
                      {key === "api_access" && on && typeof p.features.api_daily_limit === "number" && (
                        <span className="text-muted"> ({p.features.api_daily_limit.toLocaleString()}/day)</span>
                      )}
                    </li>
                  );
                })}
              </ul>
              <Button className="mt-6 w-full" variant={featured ? "primary" : "outline"} loading={busy === p.code}
                disabled={current === p.code} onClick={() => choose(p)}>
                {current === p.code ? "Current plan" : p.price_minor === 0 ? "Start free" : `Choose ${p.name}`}
              </Button>
            </div>
          );
        })}
      </div>
      <p className="mt-4 text-center text-xs text-subtle">
        Prices in Nigerian Naira, billed monthly via Paystack (cards, bank transfer, USSD; international cards supported). Cancel anytime -
        access continues to the end of the paid period.
      </p>
    </div>
  );
}
