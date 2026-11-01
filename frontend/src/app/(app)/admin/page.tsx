"use client";

import { useState } from "react";
import { Play } from "lucide-react";
import { PageHeader } from "@/components/layout/app-shell";
import { Badge, DemoBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Pager, Stat, Table, Tabs, Td, Th } from "@/components/ui/data";
import { Alert, EmptyState, Skeleton } from "@/components/ui/feedback";
import { Field, Input, Select, Switch } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { kickoff, money, num, pct, relative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Competition, Fixture, Page, Plan, User } from "@/lib/types";

type Tab = "overview" | "users" | "plans" | "competitions" | "providers" | "settings" | "models" | "bookmakers" | "audit";

function useAction() {
  const [msg, setMsg] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<unknown>, ok = "Saved") => {
    setBusy(key); setMsg(null);
    try { await fn(); setMsg({ tone: "success", text: ok }); }
    catch (e) { setMsg({ tone: "danger", text: e instanceof ApiError ? e.message : "Action failed" }); }
    finally { setBusy(null); }
  };
  return { msg, busy, run };
}

function Overview() {
  const { data } = useApi<Record<string, number | string | boolean>>("/admin/overview");
  const missing = useApi<Page<Fixture>>("/admin/missing-events", { page_size: 10 });
  if (!data) return <Skeleton className="h-40" />;
  const tiles: [string, string][] = [["users", "Users"], ["verified_users", "Verified"], ["active_subscriptions", "Active subscriptions"], ["competitions", "Competitions"],
    ["fixtures", "Fixtures"], ["upcoming_fixtures", "Upcoming"], ["predictions", "Predictions"], ["settled_predictions", "Settled"],
    ["provider_errors_24h", "Provider errors (24h)"], ["missing_timelines", "Missing/inconsistent timelines"]];
  return (
    <div className="space-y-6">
      {data.demo_mode && <Alert tone="demo" title="Demo mode">Set FOOTBALL_PROVIDER and the provider API key to switch to live data.</Alert>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">{tiles.map(([k, l]) => <Stat key={k} label={l} value={String(data[k])} />)}</div>
      <Card>
        <CardHeader title="Fixtures with missing or inconsistent event timelines" description="Excluded from features and settled as unresolved until corrected" />
        {!missing.data?.items.length ? <EmptyState title="All finished fixtures have reconciled timelines" /> : (
          <Table><thead><tr><Th>Kick-off</Th><Th>Fixture</Th><Th>Competition</Th><Th>Score</Th><Th>Timeline</Th></tr></thead>
            <tbody>{missing.data.items.map((f) => (
              <tr key={f.id}><Td className="text-xs text-muted">{kickoff(f.kickoff_at)}</Td><Td>{f.home_team.name} vs {f.away_team.name}</Td><Td className="text-xs">{f.competition.name}</Td>
                <Td className="tabular">{f.score.home ?? "-"}-{f.score.away ?? "-"}</Td><Td><Badge tone="warn">{f.timeline_status}</Badge></Td></tr>))}</tbody></Table>
        )}
      </Card>
    </div>
  );
}

function Users() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const { data, reload } = useApi<Page<User & { is_active: boolean }>>("/admin/users", { q, page, page_size: 20 });
  const { user: me } = useAuth();
  const a = useAction();
  const update = (id: number, body: object) => a.run(String(id), async () => { await api(`/admin/users/${id}`, { method: "PATCH", body }); reload(); }, "User updated");
  return (
    <Card>
      <CardHeader title="Users" action={<Input placeholder="Search email or name" value={q} onChange={(e) => { setPage(1); setQ(e.target.value); }} className="h-8 w-56" />} />
      {a.msg && <CardBody className="pb-0"><Alert tone={a.msg.tone}>{a.msg.text}</Alert></CardBody>}
      <Table>
        <thead><tr><Th>User</Th><Th>Joined</Th><Th>Verified</Th><Th>Plan</Th><Th>Role</Th><Th>Active</Th></tr></thead>
        <tbody>{data?.items.map((u) => (
          <tr key={u.id}>
            <Td><p className="font-medium">{u.email}</p><p className="text-xs text-subtle">{u.full_name}</p></Td>
            <Td className="text-xs text-muted">{u.created_at && new Date(u.created_at).toLocaleDateString()}</Td>
            <Td>{u.email_verified ? <Badge tone="brand">yes</Badge> : <Badge>no</Badge>}</Td>
            <Td><Select className="h-8 w-28 text-xs" value={u.entitlements?.plan} onChange={(e) => update(u.id, { plan_code: e.target.value })}>
              {["free", "starter", "pro", "elite"].map((p) => <option key={p} value={p}>{p}</option>)}</Select></Td>
            <Td><Select className="h-8 w-24 text-xs" value={u.role} disabled={u.id === me?.id} onChange={(e) => update(u.id, { role: e.target.value })}>
              <option value="user">user</option><option value="admin">admin</option></Select></Td>
            <Td><Switch label="Active" checked={u.is_active} disabled={u.id === me?.id} onChange={(v) => update(u.id, { is_active: v })} /></Td>
          </tr>))}</tbody>
      </Table>
      {data && <Pager page={data.page} pages={data.pages} onPage={setPage} />}
    </Card>
  );
}

function Plans() {
  const { data, reload } = useApi<Plan[]>("/admin/plans");
  const a = useAction();
  if (!data) return <Skeleton className="h-40" />;
  return (
    <Card>
      <CardHeader title="Plans & pricing" description="Changes apply to new checkouts immediately and are audited." />
      {a.msg && <CardBody className="pb-0"><Alert tone={a.msg.tone}>{a.msg.text}</Alert></CardBody>}
      <CardBody className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {data.map((p) => (
          <form key={p.code} className="space-y-3 rounded-[var(--radius-md)] border border-border bg-surface-2 p-4"
            onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget);
              a.run(p.code, async () => { await api(`/admin/plans/${p.code}`, { method: "PATCH", body: {
                name: f.get("name"), description: f.get("description"), price_minor: Math.round(Number(f.get("price")) * 100), is_active: f.get("active") === "on" } }); reload(); }, `${p.name} updated`); }}>
            <p className="text-xs font-semibold uppercase text-muted">{p.code} · now {money(p.price, p.currency)}</p>
            <Field label="Name"><Input name="name" defaultValue={p.name} /></Field>
            <Field label={`Monthly price (${p.currency})`}><Input name="price" type="number" min={0} step="1" defaultValue={p.price} /></Field>
            <Field label="Description"><Input name="description" defaultValue={p.description ?? ""} /></Field>
            <label className="flex items-center gap-2 text-xs text-muted"><input type="checkbox" name="active" defaultChecked={p.is_active} className="accent-[var(--color-brand-500)]" /> Active</label>
            <Button size="sm" type="submit" loading={a.busy === p.code}>Save</Button>
          </form>
        ))}
      </CardBody>
    </Card>
  );
}

function Competitions() {
  const { data, reload } = useApi<(Competition & { fixtures: number; finished: number; timeline_coverage: number | null })[]>("/admin/competitions");
  const a = useAction();
  const patch = (id: number, body: object) => a.run(String(id), async () => { await api(`/admin/competitions/${id}`, { method: "PATCH", body }); reload(); }, "Competition updated");
  return (
    <Card>
      <CardHeader title="Competitions" description="Eligibility for scanning and data-quality tier" />
      {a.msg && <CardBody className="pb-0"><Alert tone={a.msg.tone}>{a.msg.text}</Alert></CardBody>}
      <Table>
        <thead><tr><Th>Competition</Th><Th>Country</Th><Th className="text-right">Fixtures</Th><Th className="text-right">Timeline coverage</Th><Th>Quality tier</Th><Th>Scan</Th></tr></thead>
        <tbody>{data?.map((c) => (
          <tr key={c.id}>
            <Td className="font-medium">{c.name} {c.is_demo && <DemoBadge />}</Td><Td className="text-xs text-muted">{c.country}</Td>
            <Td className="tabular text-right">{c.fixtures}</Td>
            <Td className="tabular text-right"><span className={c.timeline_coverage != null && c.timeline_coverage < 0.8 ? "text-warn" : ""}>{pct(c.timeline_coverage)}</span></Td>
            <Td><Select className="h-8 w-28 text-xs" value={c.data_quality_tier} onChange={(e) => patch(c.id, { data_quality_tier: e.target.value })}>
              {["high", "medium", "low", "unknown"].map((t) => <option key={t} value={t}>{t}</option>)}</Select></Td>
            <Td><Switch label="Enabled" checked={c.is_enabled} onChange={(v) => patch(c.id, { is_enabled: v })} /></Td>
          </tr>))}</tbody>
      </Table>
    </Card>
  );
}

interface Providers {
  football: { name: string; label: string; configured: boolean; active: boolean; env: string | null }[];
  odds_provider: string; payment_provider: string;
  health_24h: Record<string, { success: number; error: number; rate_limited: number; avg_latency_ms: number | null }>;
  recent_runs: { id: number; job: string; provider: string; status: string; started_at: string; stats: Record<string, unknown>; error: string | null }[];
}

function ProvidersTab() {
  const { data, reload } = useApi<Providers>("/admin/providers");
  const errors = useApi<Page<{ id: number; provider: string; operation: string; status: string; http_status: number | null; error: string | null; created_at: string }>>("/admin/integration-errors", { page_size: 10 });
  const a = useAction();
  const job = (name: string) => a.run(name, async () => { const r = await api<{ result: unknown }>("/admin/jobs", { method: "POST", body: { job: name } }); reload(); return r; }, `Job "${name}" completed`);
  if (!data) return <Skeleton className="h-40" />;
  return (
    <div className="space-y-6">
      {a.msg && <Alert tone={a.msg.tone}>{a.msg.text}</Alert>}
      <Card>
        <CardHeader title="Data providers" action={<div className="flex flex-wrap gap-2">{["sync", "scan", "settle", "backtest"].map((j) => (
          <Button key={j} size="sm" variant="outline" loading={a.busy === j} onClick={() => job(j)}><Play className="h-3.5 w-3.5" />{j}</Button>))}</div>} />
        <Table>
          <thead><tr><Th>Provider</Th><Th>Configured</Th><Th>Active</Th><Th>Credential</Th><Th className="text-right">OK / errors (24h)</Th><Th className="text-right">Latency</Th></tr></thead>
          <tbody>{data.football.map((p) => { const h = data.health_24h[p.name]; return (
            <tr key={p.name}><Td className="font-medium">{p.label}</Td><Td>{p.configured ? <Badge tone="brand">yes</Badge> : <Badge tone="warn">missing key</Badge>}</Td>
              <Td>{p.active ? <Badge tone="brand">active</Badge> : <span className="text-xs text-subtle">-</span>}</Td><Td className="font-[family-name:var(--font-mono)] text-xs text-muted">{p.env ?? "n/a"}</Td>
              <Td className="tabular text-right text-xs">{h ? `${h.success} / ${h.error + h.rate_limited}` : "-"}</Td><Td className="tabular text-right text-xs">{h?.avg_latency_ms ? `${h.avg_latency_ms} ms` : "-"}</Td></tr>); })}</tbody>
        </Table>
        <CardBody className="flex flex-wrap gap-6 text-sm text-muted">
          <span>Odds provider: <span className="text-fg">{data.odds_provider}</span></span>
          <span>Payments: <span className="text-fg">{data.payment_provider}</span></span>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Recent synchronisation runs" />
        <Table><thead><tr><Th>Job</Th><Th>Provider</Th><Th>Status</Th><Th>Started</Th><Th>Stats</Th></tr></thead>
          <tbody>{data.recent_runs.map((r) => (
            <tr key={r.id}><Td className="text-sm">{r.job}</Td><Td className="text-xs text-muted">{r.provider}</Td>
              <Td><Badge tone={r.status === "success" ? "brand" : r.status === "failed" ? "danger" : "warn"}>{r.status}</Badge></Td>
              <Td className="text-xs text-muted">{relative(r.started_at)}</Td>
              <Td className="max-w-md truncate font-[family-name:var(--font-mono)] text-[11px] text-subtle" title={JSON.stringify(r.stats)}>{r.error ?? JSON.stringify(r.stats)}</Td></tr>))}</tbody></Table>
      </Card>
      <Card>
        <CardHeader title="Integration errors" />
        {!errors.data?.items.length ? <EmptyState title="No integration errors recorded" /> : (
          <Table><thead><tr><Th>When</Th><Th>Provider</Th><Th>Operation</Th><Th>HTTP</Th><Th>Error</Th></tr></thead>
            <tbody>{errors.data.items.map((e) => (<tr key={e.id}><Td className="text-xs text-muted">{relative(e.created_at)}</Td><Td>{e.provider}</Td><Td className="text-xs">{e.operation}</Td>
              <Td className="tabular">{e.http_status ?? "-"}</Td><Td className="max-w-md truncate text-xs text-danger">{e.error}</Td></tr>))}</tbody></Table>
        )}
      </Card>
    </div>
  );
}

interface SettingsRes {
  "scanner.thresholds": { MARKET_A: { qualified_min_probability: number; watchlist_min_probability: number }; MARKET_B: { qualified_min_probability: number; watchlist_min_probability: number };
    qualified_min_team_sample: number; watchlist_min_team_sample: number; qualified_min_data_quality: string; lookahead_hours: number };
  "model.baseline": Record<string, number>;
  "platform.flags": { registrations_open: boolean; maintenance_mode: boolean };
  settlement_rules: { id: number; code: string; description: string; cutoff_seconds: number; minute_convention: string; is_default: boolean }[];
}

function SettingsTab() {
  const { data, reload } = useApi<SettingsRes>("/admin/settings");
  const a = useAction();
  if (!data) return <Skeleton className="h-60" />;
  const t = data["scanner.thresholds"];
  const m = data["model.baseline"];
  const saveThresholds = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const n = (k: string) => Number(f.get(k));
    a.run("thr", async () => { await api("/admin/settings/scanner.thresholds", { method: "PUT", body: {
      MARKET_A: { qualified_min_probability: n("a_q") / 100, watchlist_min_probability: n("a_w") / 100 },
      MARKET_B: { qualified_min_probability: n("b_q") / 100, watchlist_min_probability: n("b_w") / 100 },
      qualified_min_team_sample: n("q_sample"), watchlist_min_team_sample: n("w_sample"),
      qualified_min_data_quality: f.get("dq"), lookahead_hours: n("lookahead") } }); reload(); }, "Thresholds saved - applied on the next scan");
  };
  const saveModel = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    a.run("model", async () => { await api("/admin/settings/model.baseline", { method: "PUT", body: Object.fromEntries(Object.keys(m).map((k) => [k, Number(f.get(k))])) }); reload(); }, "Model parameters saved");
  };
  return (
    <div className="space-y-6">
      {a.msg && <Alert tone={a.msg.tone}>{a.msg.text}</Alert>}
      <Card>
        <CardHeader title="Scanner thresholds" description="Qualified requires probability, sample size and data quality; watchlist requires probability only." />
        <CardBody>
          <form onSubmit={saveThresholds} className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Field label="Market A qualified %"><Input name="a_q" type="number" step="0.1" defaultValue={(t.MARKET_A.qualified_min_probability * 100).toFixed(1)} /></Field>
            <Field label="Market A watchlist %"><Input name="a_w" type="number" step="0.1" defaultValue={(t.MARKET_A.watchlist_min_probability * 100).toFixed(1)} /></Field>
            <Field label="Market B qualified %"><Input name="b_q" type="number" step="0.1" defaultValue={(t.MARKET_B.qualified_min_probability * 100).toFixed(1)} /></Field>
            <Field label="Market B watchlist %"><Input name="b_w" type="number" step="0.1" defaultValue={(t.MARKET_B.watchlist_min_probability * 100).toFixed(1)} /></Field>
            <Field label="Qualified min. team sample"><Input name="q_sample" type="number" defaultValue={t.qualified_min_team_sample} /></Field>
            <Field label="Minimum sample (else excluded)"><Input name="w_sample" type="number" defaultValue={t.watchlist_min_team_sample} /></Field>
            <Field label="Qualified min. data quality"><Select name="dq" defaultValue={t.qualified_min_data_quality}>{["low", "medium", "high"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
            <Field label="Lookahead (hours)"><Input name="lookahead" type="number" defaultValue={t.lookahead_hours} /></Field>
            <div><Button type="submit" loading={a.busy === "thr"}>Save thresholds</Button></div>
          </form>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Baseline model parameters" description="Changing parameters changes the input version: upcoming fixtures are re-predicted (old predictions are kept)." />
        <CardBody>
          <form onSubmit={saveModel} className="grid grid-cols-2 gap-4 md:grid-cols-5">
            {Object.entries(m).map(([k, v]) => <Field key={k} label={k.replaceAll("_", " ")}><Input name={k} type="number" step="any" defaultValue={v} /></Field>)}
            <div className="self-end"><Button type="submit" loading={a.busy === "model"}>Save</Button></div>
          </form>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Settlement rules" description="Bookmakers settle five-minute markets differently - choose the default rule." />
        <Table><thead><tr><Th>Code</Th><Th>Description</Th><Th>Cutoff</Th><Th>Minute convention</Th><Th /></tr></thead>
          <tbody>{data.settlement_rules.map((r) => (
            <tr key={r.id}><Td className="font-[family-name:var(--font-mono)] text-xs">{r.code}</Td><Td className="text-sm">{r.description}</Td><Td className="tabular">{r.cutoff_seconds}s</Td><Td className="text-xs">{r.minute_convention}</Td>
              <Td>{r.is_default ? <Badge tone="brand">default</Badge> : <Button size="sm" variant="outline" onClick={() => a.run("rule", async () => { await api("/admin/settlement-rules/default", { method: "PUT", body: { rule_id: r.id } }); reload(); }, "Default rule changed")}>Make default</Button>}</Td></tr>))}</tbody></Table>
      </Card>
      <Card>
        <CardHeader title="Platform flags" />
        <CardBody className="space-y-3">
          {(["registrations_open", "maintenance_mode"] as const).map((k) => (
            <div key={k} className="flex max-w-md items-center justify-between rounded-[var(--radius-md)] border border-border bg-surface-2 px-3 py-2.5 text-sm">
              {k.replace("_", " ")}
              <Switch label={k} checked={data["platform.flags"][k]} onChange={(v) => a.run("flags", async () => { await api("/admin/settings/platform.flags", { method: "PUT", body: { ...data["platform.flags"], [k]: v } }); reload(); })} />
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  );
}

function Models() {
  const { data } = useApi<{ models: { id: number; market: string; name: string; version: string; algorithm: string; is_active: boolean; calibration_status: string; predictions: number;
    walk_forward: { metric: string; value: number | null; sample_size: number; is_demo: boolean }[] }[] }>("/admin/model-performance");
  if (!data) return <Skeleton className="h-40" />;
  return (
    <Card>
      <CardHeader title="Model versions" description="Compare walk-forward metrics across versions" />
      <Table><thead><tr><Th>Market</Th><Th>Model</Th><Th>Status</Th><Th className="text-right">Predictions</Th><Th className="text-right">Brier</Th><Th className="text-right">Log loss</Th><Th className="text-right">ECE</Th><Th className="text-right">Backtest n</Th></tr></thead>
        <tbody>{data.models.map((mv) => { const g = (k: string) => mv.walk_forward.find((x) => x.metric === k); return (
          <tr key={mv.id}><Td>{mv.market}</Td><Td>{mv.name} <span className="text-xs text-subtle">v{mv.version} · {mv.algorithm}</span></Td>
            <Td>{mv.is_active ? <Badge tone="brand">active</Badge> : <Badge>inactive</Badge>} <Badge>{mv.calibration_status}</Badge></Td>
            <Td className="tabular text-right">{mv.predictions}</Td><Td className="tabular text-right">{num(g("brier")?.value)}</Td><Td className="tabular text-right">{num(g("log_loss")?.value)}</Td>
            <Td className="tabular text-right">{num(g("ece")?.value)}</Td><Td className="tabular text-right">{g("brier")?.sample_size ?? "-"} {g("brier")?.is_demo && <DemoBadge />}</Td></tr>); })}</tbody></Table>
    </Card>
  );
}

function Bookmakers() {
  const { data, reload } = useApi<{ id: number; code: string; name: string; website_url: string | null; deep_link_template: string | null; is_active: boolean }[]>("/admin/bookmakers");
  const a = useAction();
  return (
    <div className="space-y-6">
      {a.msg && <Alert tone={a.msg.tone}>{a.msg.text}</Alert>}
      <Card>
        <CardHeader title="Add bookmaker" description="Only add operators you have an authorised referral / deep-link agreement with." />
        <CardBody>
          <form className="grid gap-3 md:grid-cols-5" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const form = e.currentTarget;
            a.run("add", async () => { await api("/admin/bookmakers", { method: "POST", body: { code: f.get("code"), name: f.get("name"), website_url: f.get("website") || null, deep_link_template: f.get("template") || null } }); form.reset(); reload(); }, "Bookmaker added"); }}>
            <Field label="Code"><Input name="code" pattern="[a-z0-9_-]{2,48}" required /></Field>
            <Field label="Name"><Input name="name" required /></Field>
            <Field label="Website"><Input name="website" type="url" placeholder="https://" /></Field>
            <Field label="Deep-link template" hint="Use {event_ref}"><Input name="template" placeholder="https://.../{event_ref}?ref=..." /></Field>
            <div className="self-start pt-6"><Button type="submit" loading={a.busy === "add"}>Add</Button></div>
          </form>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Bookmakers" />
        {!data?.length ? <EmptyState title="No bookmakers configured">Odds and sportsbook links appear once bookmakers and an odds provider are configured.</EmptyState> : (
          <Table><thead><tr><Th>Name</Th><Th>Code</Th><Th>Link template</Th><Th>Active</Th></tr></thead>
            <tbody>{data.map((b) => (<tr key={b.id}><Td>{b.name}</Td><Td className="font-[family-name:var(--font-mono)] text-xs">{b.code}</Td><Td className="max-w-xs truncate text-xs text-muted">{b.deep_link_template ?? "-"}</Td>
              <Td><Switch label="Active" checked={b.is_active} onChange={(v) => a.run(String(b.id), async () => { await api(`/admin/bookmakers/${b.id}`, { method: "PATCH", body: { is_active: v } }); reload(); })} /></Td></tr>))}</tbody></Table>
        )}
      </Card>
    </div>
  );
}

function Audit() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const { data } = useApi<Page<{ id: number; actor_user_id: number | null; action: string; entity_type: string | null; entity_id: string | null; details: object; ip_address: string | null; created_at: string }>>("/admin/audit-logs", { page, page_size: 25, action });
  return (
    <Card>
      <CardHeader title="Audit log" action={<Input className="h-8 w-48" placeholder="Filter action prefix" value={action} onChange={(e) => { setPage(1); setAction(e.target.value); }} />} />
      <Table><thead><tr><Th>When</Th><Th>Actor</Th><Th>Action</Th><Th>Entity</Th><Th>Details</Th><Th>IP</Th></tr></thead>
        <tbody>{data?.items.map((l) => (<tr key={l.id}><Td className="whitespace-nowrap text-xs text-muted">{new Date(l.created_at).toLocaleString()}</Td><Td className="tabular text-xs">{l.actor_user_id ?? "system"}</Td>
          <Td className="font-[family-name:var(--font-mono)] text-xs">{l.action}</Td><Td className="text-xs">{l.entity_type} {l.entity_id}</Td>
          <Td className="max-w-sm truncate font-[family-name:var(--font-mono)] text-[11px] text-subtle" title={JSON.stringify(l.details)}>{JSON.stringify(l.details)}</Td><Td className="text-xs text-subtle">{l.ip_address}</Td></tr>))}</tbody></Table>
      {data && <Pager page={data.page} pages={data.pages} onPage={setPage} />}
    </Card>
  );
}

export default function AdminPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  if (user?.role !== "admin") return <Alert tone="danger">Administrator access required.</Alert>;
  return (
    <>
      <PageHeader title="Administration" description="Users, billing, data providers, scanner configuration and audit trail." />
      <div className="mb-5 overflow-x-auto">
        <Tabs value={tab} onChange={setTab} options={[
          { value: "overview", label: "Overview" }, { value: "users", label: "Users" }, { value: "plans", label: "Plans" }, { value: "competitions", label: "Competitions" },
          { value: "providers", label: "Providers & sync" }, { value: "settings", label: "Settings" }, { value: "models", label: "Models" },
          { value: "bookmakers", label: "Bookmakers" }, { value: "audit", label: "Audit log" },
        ]} />
      </div>
      {tab === "overview" && <Overview />}
      {tab === "users" && <Users />}
      {tab === "plans" && <Plans />}
      {tab === "competitions" && <Competitions />}
      {tab === "providers" && <ProvidersTab />}
      {tab === "settings" && <SettingsTab />}
      {tab === "models" && <Models />}
      {tab === "bookmakers" && <Bookmakers />}
      {tab === "audit" && <Audit />}
    </>
  );
}
