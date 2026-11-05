"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ExternalLink } from "lucide-react";
import { OddsHistoryChart } from "@/components/charts/charts";
import { Badge, DemoBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, Tabs, Td, Th } from "@/components/ui/data";
import { Dialog } from "@/components/ui/dialog";
import { Alert, EmptyState, Skeleton } from "@/components/ui/feedback";
import { Checkbox } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { MARKET_LABEL, money, pct, relative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { FixtureOdds, LimitStatus, Market, OddsRow } from "@/lib/types";

export function EdgeValue({ edge }: { edge: number | null | undefined }) {
  if (edge === null || edge === undefined) return <span className="text-subtle">-</span>;
  return <span className={cn("tabular font-semibold", edge > 0 ? "text-brand-400" : "text-muted")}>{edge > 0 ? "+" : ""}{(edge * 100).toFixed(1)}%</span>;
}

interface OpenResult { url: string; bet_prefill: { fixture_id: number; market: Market; decimal_odds: number; bookmaker_id: number }; notice: string; is_demo: boolean }

function limitLine(s: LimitStatus): string[] {
  const out: string[] = [];
  if (s.daily.limit !== null) out.push(`24h: ${money(s.daily.used)} of ${money(s.daily.limit)}`);
  if (s.monthly.limit !== null) out.push(`30 days: ${money(s.monthly.used)} of ${money(s.monthly.limit)}`);
  return out;
}

/** Responsible-gambling interstitial shown before any link-out to a sportsbook. */
export function OpenSportsbookDialog({ fixtureId, row, limits, onClose }: { fixtureId: number; row: OddsRow | null; limits: LimitStatus; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsAck, setNeedsAck] = useState(false);
  const [ack, setAck] = useState(false);
  const [done, setDone] = useState<OpenResult | null>(null);
  const close = () => { setError(null); setNeedsAck(false); setAck(false); setDone(null); onClose(); };
  if (!row) return null;

  const go = async () => {
    setBusy(true); setError(null);
    try {
      const res = await api<OpenResult>(`/odds/${fixtureId}/open`, { method: "POST", body: { bookmaker_code: row.bookmaker.code, market: row.market, acknowledge_limits: ack } });
      window.open(res.url, "_blank", "noopener,noreferrer");
      setDone(res);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && (e.detail as { detail?: { code?: string } })?.detail?.code === "limit_reached") setNeedsAck(true);
      setError(e instanceof ApiError ? e.message : "Could not open the sportsbook");
    } finally { setBusy(false); }
  };

  const prefill = done ? `/account?tab=bets&fixture=${done.bet_prefill.fixture_id}&market=${done.bet_prefill.market}&odds=${done.bet_prefill.decimal_odds}&bookmaker=${done.bet_prefill.bookmaker_id}` : "";
  return (
    <Dialog open onClose={close} title={done ? "Sportsbook opened in a new tab" : `Continue to ${row.bookmaker.name}?`}>
      {done ? (
        <div className="space-y-4 text-sm">
          <p className="text-muted">{done.notice}</p>
          <p>If you place a bet, you can record it for your own tracking and limits:</p>
          <div className="flex gap-2">
            <Link href={prefill} className="inline-flex h-10 items-center rounded-[var(--radius-md)] bg-brand-500 px-4 text-sm font-semibold text-on-brand hover:bg-brand-400">Record this bet</Link>
            <Button variant="ghost" onClick={close}>Not now</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4 text-sm">
          <div className="rounded-[var(--radius-md)] border border-border bg-surface-2 p-3">
            <p className="font-semibold">{MARKET_LABEL[row.market]} · odds <span className="tabular">{row.decimal_odds.toFixed(2)}</span></p>
            <p className="mt-0.5 text-xs text-muted">Price checked {relative(row.checked_at)} · it may have changed - verify it on the sportsbook.</p>
          </div>
          <ul className="list-disc space-y-1.5 pl-5 text-muted">
            <li>You are leaving First5Minute. We never place bets, hold funds or ask for sportsbook passwords.</li>
            <li>Estimates are statistical and can be wrong. Only stake what you can afford to lose. 18+.</li>
            {limitLine(limits).length > 0 && <li>Your limits: {limitLine(limits).join(" · ")}.</li>}
          </ul>
          {row.rule_mismatch && <Alert tone="warn" title="Different settlement rule">{row.rule_note}</Alert>}
          {row.is_demo && <Alert tone="demo" title="Demo sportsbook">This is synthetic development data; the link opens example.com.</Alert>}
          {error && <Alert tone={needsAck ? "warn" : "danger"}>{error}</Alert>}
          {needsAck && <Checkbox checked={ack} onChange={(e) => setAck(e.target.checked)} label="I understand I have reached a stake limit I set, and I still want to continue." />}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={close}>Cancel</Button>
            <Button onClick={go} loading={busy} disabled={needsAck && !ack}>Continue to {row.bookmaker.name} <ExternalLink className="h-3.5 w-3.5" /></Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

export function OddsPanel({ fixtureId }: { fixtureId: number }) {
  const { data, loading, error, reload } = useApi<FixtureOdds>(`/odds/${fixtureId}`);
  const [market, setMarket] = useState<Market>("MARKET_A");
  const [target, setTarget] = useState<OddsRow | null>(null);
  if (loading) return <Skeleton className="h-40" />;
  if (error) return <Alert tone="danger">{error.message}</Alert>;
  if (!data) return null;
  if (!data.odds.length) return <EmptyState title="No odds available">{data.message}</EmptyState>;

  const summary = data.markets[market];
  const rows = data.odds.filter((r) => r.market === market);
  const hasDemo = data.odds.some((r) => r.is_demo);
  return (
    <div className="space-y-4">
      {hasDemo && <Alert tone="demo" title="Demo odds">Synthetic prices derived from the model plus a margin - they never contain value and are not real bookmakers.</Alert>}
      {data.self_excluded && <Alert tone="warn">Sportsbook links are disabled while you are self-excluded.</Alert>}
      <div className="flex items-center justify-between gap-3">
        <Tabs value={market} onChange={setMarket} options={[{ value: "MARKET_A", label: "No goal 0-5'" }, { value: "MARKET_B", label: "Level at 5'" }]} />
        <button className="cursor-pointer text-xs text-brand-400 hover:underline" onClick={reload}>Refresh</button>
      </div>
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["Model estimate", pct(summary.probability)],
            ["Model fair odds", summary.fair_odds ? summary.fair_odds.toFixed(2) : "-"],
            ["Best fresh odds", summary.best ? `${summary.best.decimal_odds.toFixed(2)}` : "none"],
          ].map(([k, v]) => (
            <div key={k} className="rounded-[var(--radius-md)] border border-border bg-surface-2 p-3"><p className="text-[11px] uppercase tracking-wide text-subtle">{k}</p><p className="tabular mt-1 text-lg font-bold">{v}</p></div>
          ))}
          <div className="rounded-[var(--radius-md)] border border-border bg-surface-2 p-3"><p className="text-[11px] uppercase tracking-wide text-subtle">Estimated edge</p><p className="mt-1 text-lg font-bold"><EdgeValue edge={summary.edge} /></p></div>
        </div>
      )}
      <Table>
        <thead><tr><Th>Sportsbook</Th><Th className="text-right">Odds</Th><Th className="text-right">Fair</Th><Th className="text-right">Edge</Th><Th className="text-right">Implied</Th><Th>Updated</Th><Th /></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.bookmaker.code + r.selection} className={cn((!r.is_available || r.is_stale) && "opacity-60")}>
              <Td className="font-medium">{r.bookmaker.name} {r.is_demo && <DemoBadge />}
                {r.rule_mismatch && <span title={r.rule_note ?? ""} className="ml-1.5 inline-flex align-middle text-warn"><AlertTriangle className="h-3.5 w-3.5" aria-label="Different settlement rule" /></span>}</Td>
              <Td className="tabular text-right font-semibold">{r.decimal_odds.toFixed(2)}</Td>
              <Td className="tabular text-right text-muted">{r.fair_odds?.toFixed(2) ?? "-"}</Td>
              <Td className="text-right"><EdgeValue edge={r.edge} /></Td>
              <Td className="tabular text-right text-muted">{pct(r.implied_probability)}</Td>
              <Td className="whitespace-nowrap text-xs text-muted">{relative(r.checked_at)} {!r.is_available ? <Badge tone="danger">suspended</Badge> : r.is_stale ? <Badge tone="warn">stale</Badge> : null}</Td>
              <Td className="text-right">{r.can_open && r.is_available ? <Button size="sm" variant="outline" onClick={() => setTarget(r)}>Open <ExternalLink className="h-3 w-3" /></Button> : <span className="text-xs text-subtle">{data.self_excluded ? "disabled" : r.is_stale || !r.is_available ? "unavailable" : "no link"}</span>}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {(data.best_history[market]?.length ?? 0) > 1 && (
        <div>
          <p className="mb-1 text-sm font-semibold">Best available odds over time</p>
          <OddsHistoryChart points={data.best_history[market]!} fair={summary?.fair_odds ?? null} />
        </div>
      )}
      <p className="text-xs text-subtle">{data.notice} Prices older than {data.max_age_minutes} minutes are marked stale and ignored for edge.</p>
      <OpenSportsbookDialog fixtureId={fixtureId} row={target} limits={data.responsible_gambling} onClose={() => { setTarget(null); reload(); }} />
    </div>
  );
}
