"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { PageHeader } from "@/components/layout/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Stat, Table, Tabs, Td, Th } from "@/components/ui/data";
import { Alert, EmptyState, Skeleton } from "@/components/ui/feedback";
import { Checkbox, Field, Input, Select, Switch } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { kickoff, MARKET_LABEL, money } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Fixture, Plan } from "@/lib/types";

type Tab = "profile" | "billing" | "saved" | "bets" | "safer" | "security";

function useSaver() {
  const [msg, setMsg] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, ok = "Saved") => {
    setBusy(true);
    setMsg(null);
    try { await fn(); setMsg({ tone: "success", text: ok }); }
    catch (e) { setMsg({ tone: "danger", text: e instanceof ApiError ? e.message : "Something went wrong" }); }
    finally { setBusy(false); }
  };
  return { msg, busy, run };
}

function Profile() {
  const { user, refresh } = useAuth();
  const s = useSaver();
  const [prefs, setPrefs] = useState(user?.notification_prefs ?? {});
  if (!user) return null;
  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    s.run(async () => {
      await api("/account/profile", { method: "PATCH", body: { full_name: f.get("full_name"), country: f.get("country") || null, timezone: f.get("timezone"), notification_prefs: prefs } });
      await refresh();
    });
  };
  return (
    <Card>
      <CardHeader title="Profile & notifications" />
      <CardBody>
        {s.msg && <Alert tone={s.msg.tone} className="mb-4">{s.msg.text}</Alert>}
        <form onSubmit={submit} className="grid max-w-2xl gap-4 sm:grid-cols-2">
          <Field label="Full name"><Input name="full_name" defaultValue={user.full_name ?? ""} maxLength={120} /></Field>
          <Field label="Email"><Input value={user.email} disabled /></Field>
          <Field label="Country (ISO code)"><Input name="country" defaultValue={user.country ?? ""} maxLength={2} /></Field>
          <Field label="Timezone"><Input name="timezone" defaultValue={user.timezone} maxLength={64} /></Field>
          <div className="space-y-3 sm:col-span-2">
            <p className="text-xs font-medium text-muted">Notifications</p>
            {[["scanner_qualified", "Newly qualified matches (Pro and above)"], ["prediction_settled", "Saved match settled"], ["email", "Also send by email"]].map(([k, label]) => (
              <div key={k} className="flex items-center justify-between rounded-[var(--radius-md)] border border-border bg-surface-2 px-3 py-2.5 text-sm">
                {label}<Switch label={label} checked={Boolean(prefs[k])} onChange={(v) => setPrefs({ ...prefs, [k]: v })} />
              </div>
            ))}
          </div>
          <div><Button type="submit" loading={s.busy}>Save changes</Button></div>
        </form>
      </CardBody>
    </Card>
  );
}

interface SubRes {
  entitlements: { plan: string; plan_name: string };
  subscription: { plan: Plan; status: string; current_period_end: string | null; cancel_at_period_end: boolean } | null;
  invoices: { id: number; amount: number; currency: string; status: string; reference: string; created_at: string; paid_at: string | null }[];
  payments_enabled: boolean;
}

function Billing() {
  const params = useSearchParams();
  const { data, loading, reload } = useApi<SubRes>("/subscriptions");
  const { refresh } = useAuth();
  const s = useSaver();
  const reference = params.get("reference");
  useEffect(() => {
    if (reference) s.run(async () => { await api(`/subscriptions/verify/${reference}`); await refresh(); reload(); }, "Payment confirmed - your plan is active.");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reference]);
  if (loading || !data) return <Skeleton className="h-48" />;
  const sub = data.subscription;
  return (
    <div className="space-y-6">
      {s.msg && <Alert tone={s.msg.tone}>{s.msg.text}</Alert>}
      <Card>
        <CardHeader title="Subscription" action={<ButtonLink href="/pricing" size="sm" variant="outline">Change plan</ButtonLink>} />
        <CardBody className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-2xl font-bold">{data.entitlements.plan_name}</p>
            {sub ? (
              <p className="mt-1 text-sm text-muted">
                {sub.cancel_at_period_end ? "Cancelled - access until " : "Renews "} {sub.current_period_end && new Date(sub.current_period_end).toLocaleDateString()}
                {" · "}{money(sub.plan.price, sub.plan.currency)}/{sub.plan.interval}
              </p>
            ) : <p className="mt-1 text-sm text-muted">Free plan - limited daily insights.</p>}
          </div>
          {sub && !sub.cancel_at_period_end && sub.status === "active" && (
            <Button variant="danger" size="sm" loading={s.busy}
              onClick={() => confirm("Cancel your subscription? Access continues until the end of the paid period.") && s.run(async () => { await api("/subscriptions/cancel", { method: "POST" }); reload(); await refresh(); }, "Subscription cancelled.")}>
              Cancel subscription
            </Button>
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Invoice history" />
        {!data.invoices.length ? <EmptyState title="No invoices yet" /> : (
          <Table>
            <thead><tr><Th>Date</Th><Th>Reference</Th><Th className="text-right">Amount</Th><Th>Status</Th></tr></thead>
            <tbody>{data.invoices.map((i) => (
              <tr key={i.id}><Td className="text-xs text-muted">{new Date(i.created_at).toLocaleDateString()}</Td><Td className="font-[family-name:var(--font-mono)] text-xs">{i.reference}</Td>
                <Td className="tabular text-right">{money(i.amount, i.currency)}</Td><Td><Badge tone={i.status === "paid" ? "brand" : i.status === "failed" ? "danger" : "neutral"}>{i.status}</Badge></Td></tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function Saved() {
  const { data, loading, reload } = useApi<{ id: number; note: string | null; fixture: Fixture }[]>("/saved-matches");
  if (loading) return <Skeleton className="h-48" />;
  return (
    <Card>
      <CardHeader title="Saved matches" />
      {!data?.length ? <EmptyState title="No saved matches">Use the bookmark icon in the scanner to save matches.</EmptyState> : (
        <Table>
          <thead><tr><Th>Kick-off</Th><Th>Fixture</Th><Th>Status</Th><Th /></tr></thead>
          <tbody>{data.map((s) => (
            <tr key={s.id}>
              <Td className="text-xs text-muted">{kickoff(s.fixture.kickoff_at)}</Td>
              <Td><Link href={`/matches/${s.fixture.id}`} className="font-medium hover:text-brand-400">{s.fixture.home_team.name} vs {s.fixture.away_team.name}</Link><p className="text-xs text-subtle">{s.fixture.competition.name}</p></Td>
              <Td className="text-xs capitalize">{s.fixture.status}</Td>
              <Td className="text-right"><button className="cursor-pointer p-1 text-muted hover:text-danger" aria-label="Remove"
                onClick={async () => { await api(`/saved-matches/${s.id}`, { method: "DELETE" }); reload(); }}><Trash2 className="h-4 w-4" /></button></Td>
            </tr>
          ))}</tbody>
        </Table>
      )}
    </Card>
  );
}

interface Bet { id: number; fixture: Fixture; market: "MARKET_A" | "MARKET_B"; decimal_odds: number; stake: number | null; currency: string; bet_reference: string | null; placed_at: string; settlement_status: string }

function Bets() {
  const { data, loading, reload } = useApi<{ items: Bet[]; summary: { total_staked: number; total_returned: number; profit: number } }>("/bets", { page_size: 50 });
  const saved = useApi<{ id: number; fixture: Fixture }[]>("/saved-matches");
  const s = useSaver();
  const [warnings, setWarnings] = useState<string[]>([]);
  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const form = e.currentTarget;
    s.run(async () => {
      const res = await api<{ warnings: string[] }>("/bets", { method: "POST", body: {
        fixture_id: Number(f.get("fixture_id")), market: f.get("market"), decimal_odds: Number(f.get("odds")),
        stake: f.get("stake") ? Number(f.get("stake")) : null, bet_reference: f.get("reference") || null, confirm: f.get("confirm") === "on" } });
      setWarnings(res.warnings);
      form.reset();
      reload();
    }, "Bet recorded");
  };
  return (
    <div className="space-y-6">
      {data && (
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Total staked" value={money(data.summary.total_staked)} />
          <Stat label="Returned" value={money(data.summary.total_returned)} />
          <Stat label="Profit / loss" value={money(data.summary.profit)} tone={data.summary.profit >= 0 ? "brand" : "warn"} />
        </div>
      )}
      <Card>
        <CardHeader title="Record a bet" description="For your own tracking. First5Minute never places bets or holds funds." />
        <CardBody>
          {s.msg && <Alert tone={s.msg.tone} className="mb-3">{s.msg.text}</Alert>}
          {warnings.map((w) => <Alert key={w} tone="warn" className="mb-3" title="Limit reached">{w} Consider taking a break.</Alert>)}
          {!saved.data?.length ? <p className="text-sm text-muted">Save a match from the scanner first, then record your bet here.</p> : (
            <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Field label="Match" className="lg:col-span-2"><Select name="fixture_id" required>{saved.data.map((sm) => <option key={sm.id} value={sm.fixture.id}>{sm.fixture.home_team.name} vs {sm.fixture.away_team.name}</option>)}</Select></Field>
              <Field label="Market"><Select name="market"><option value="MARKET_A">{MARKET_LABEL.MARKET_A}</option><option value="MARKET_B">{MARKET_LABEL.MARKET_B}</option></Select></Field>
              <Field label="Decimal odds"><Input name="odds" type="number" step="0.01" min="1.01" required /></Field>
              <Field label="Stake (optional)"><Input name="stake" type="number" step="0.01" min="0" /></Field>
              <Field label="Bet reference (optional)" className="lg:col-span-2"><Input name="reference" maxLength={128} /></Field>
              <Checkbox name="confirm" required className="lg:col-span-2 self-end" label="I placed this bet myself with the sportsbook." />
              <div className="self-end"><Button type="submit" loading={s.busy}>Record</Button></div>
            </form>
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Your bets" />
        {loading ? <CardBody><Skeleton className="h-32" /></CardBody> : !data?.items.length ? <EmptyState title="No bets recorded" /> : (
          <Table>
            <thead><tr><Th>Placed</Th><Th>Fixture</Th><Th>Market</Th><Th className="text-right">Odds</Th><Th className="text-right">Stake</Th><Th>Settlement</Th></tr></thead>
            <tbody>{data.items.map((b) => (
              <tr key={b.id}>
                <Td className="text-xs text-muted">{new Date(b.placed_at).toLocaleDateString()}</Td>
                <Td className="text-sm">{b.fixture.home_team.name} vs {b.fixture.away_team.name}</Td>
                <Td className="text-xs">{MARKET_LABEL[b.market]}</Td>
                <Td className="tabular text-right">{b.decimal_odds.toFixed(2)}</Td>
                <Td className="tabular text-right">{b.stake != null ? money(b.stake, b.currency) : "-"}</Td>
                <Td>
                  <Select className="h-8 w-28 text-xs" value={b.settlement_status}
                    onChange={async (e) => { await api(`/bets/${b.id}`, { method: "PATCH", body: { settlement_status: e.target.value } }); reload(); }}>
                    {["pending", "won", "lost", "void"].map((x) => <option key={x} value={x}>{x}</option>)}
                  </Select>
                </Td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function Safer() {
  const { user, refresh } = useAuth();
  const s = useSaver();
  if (!user) return null;
  const rg = user.responsible_gambling;
  const excluded = rg.self_excluded_until && new Date(rg.self_excluded_until) > new Date();
  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const num = (k: string) => (f.get(k) ? Number(f.get(k)) : null);
    const exclude = num("self_exclude_days");
    if (exclude && !confirm(`Self-exclude for ${exclude} days? This cannot be undone early.`)) return;
    s.run(async () => {
      await api("/account/responsible-gambling", { method: "PUT", body: {
        daily_stake_limit: num("daily"), monthly_stake_limit: num("monthly"), reality_check_minutes: num("reality"), self_exclude_days: exclude } });
      await refresh();
    });
  };
  return (
    <Card>
      <CardHeader title="Responsible gambling" description="Tools to stay in control. Limits apply to bet tracking and sportsbook links." />
      <CardBody>
        {excluded && <Alert tone="warn" className="mb-4" title="Self-exclusion active">Until {new Date(rg.self_excluded_until!).toLocaleDateString()}. Sportsbook links and bet tracking are disabled.</Alert>}
        {s.msg && <Alert tone={s.msg.tone} className="mb-4">{s.msg.text}</Alert>}
        <form onSubmit={submit} className="grid max-w-2xl gap-4 sm:grid-cols-2">
          <Field label="24-hour stake limit (₦)"><Input name="daily" type="number" min={0} defaultValue={rg.daily_stake_limit ?? ""} /></Field>
          <Field label="30-day stake limit (₦)"><Input name="monthly" type="number" min={0} defaultValue={rg.monthly_stake_limit ?? ""} /></Field>
          <Field label="Reality check reminder"><Select name="reality" defaultValue={rg.reality_check_minutes ?? ""}><option value="">Off</option>{[15, 30, 60, 120].map((m) => <option key={m} value={m}>Every {m} minutes</option>)}</Select></Field>
          <Field label="Self-exclude" hint="Pauses sportsbook links and bet tracking."><Select name="self_exclude_days" defaultValue=""><option value="">No exclusion</option>{[1, 7, 30, 90, 180, 365].map((d) => <option key={d} value={d}>{d} day{d > 1 && "s"}</option>)}</Select></Field>
          <div><Button type="submit" loading={s.busy}>Save preferences</Button></div>
        </form>
        <p className="mt-6 text-xs text-subtle">If gambling is causing harm, contact a local support service. First5Minute is for adults 18+ only.</p>
      </CardBody>
    </Card>
  );
}

function Security() {
  const s = useSaver();
  const { user } = useAuth();
  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const form = e.currentTarget;
    if (f.get("new") !== f.get("confirm")) return;
    s.run(async () => { await api("/auth/change-password", { method: "POST", body: { current_password: f.get("current"), new_password: f.get("new") } }); form.reset(); },
      "Password changed. Other sessions were signed out.");
  };
  return (
    <Card>
      <CardHeader title="Account security" description={user?.last_login_at ? `Last sign-in ${new Date(user.last_login_at).toLocaleString()}` : undefined} />
      <CardBody>
        {s.msg && <Alert tone={s.msg.tone} className="mb-4">{s.msg.text}</Alert>}
        <form onSubmit={submit} className="grid max-w-md gap-4">
          <Field label="Current password"><Input name="current" type="password" autoComplete="current-password" required /></Field>
          <Field label="New password" hint="At least 10 characters with upper and lower case letters and a digit."><Input name="new" type="password" autoComplete="new-password" minLength={10} required /></Field>
          <Field label="Confirm new password"><Input name="confirm" type="password" autoComplete="new-password" required /></Field>
          <div><Button type="submit" loading={s.busy}>Change password</Button></div>
        </form>
      </CardBody>
    </Card>
  );
}

function AccountInner() {
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>(params.get("reference") ? "billing" : "profile");
  return (
    <>
      <PageHeader title="Account" description="Profile, subscription, saved matches and safer-gambling controls." />
      <div className="mb-5 overflow-x-auto">
        <Tabs value={tab} onChange={setTab} options={[
          { value: "profile", label: "Profile" }, { value: "billing", label: "Subscription" }, { value: "saved", label: "Saved matches" },
          { value: "bets", label: "Bet tracking" }, { value: "safer", label: "Responsible gambling" }, { value: "security", label: "Security" },
        ]} />
      </div>
      {tab === "profile" && <Profile />}
      {tab === "billing" && <Billing />}
      {tab === "saved" && <Saved />}
      {tab === "bets" && <Bets />}
      {tab === "safer" && <Safer />}
      {tab === "security" && <Security />}
    </>
  );
}

export default function AccountPage() {
  return <Suspense><AccountInner /></Suspense>;
}
