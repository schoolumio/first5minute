"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Scale } from "lucide-react";
import { PageHeader } from "@/components/layout/app-shell";
import { EdgeValue } from "@/components/match/odds-panel";
import { CategoryBadge, DemoBadge } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";
import { Pager, ProbabilityValue, Table, Td, Th } from "@/components/ui/data";
import { Alert, EmptyState, Skeleton, UpgradeNotice } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { kickoff, MARKET_LABEL, relative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Category, Fixture, Market, Page } from "@/lib/types";

interface BoardItem {
  prediction_id: number; fixture: Fixture; market: Market; probability: number; category: Category; fair_odds: number; edge: number | null;
  calibration_status: string; is_demo: boolean;
  best: { decimal_odds: number; bookmaker: string; captured_at: string; n_books: number; is_demo: boolean };
}
type Board = Page<BoardItem> & { max_age_minutes: number; provider_configured: boolean; message: string | null; notice: string };

export default function OddsPage() {
  const [f, setF] = useState({ market: "", min_edge: "", sort: "edge" });
  const [page, setPage] = useState(1);
  const query = useMemo(() => ({ market: f.market, min_edge: f.min_edge === "" ? "" : Number(f.min_edge) / 100, sort: f.sort, page, page_size: 25 }), [f, page]);
  const { data, loading, error } = useApi<Board>("/odds", query);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setPage(1); setF({ ...f, [k]: e.target.value }); };

  return (
    <>
      <PageHeader title="Odds comparison" description="Best fresh price per scanner prediction across approved sportsbooks, next to the model's fair odds." />
      {error?.status === 402 ? <UpgradeNotice feature="Odds comparison" /> : (
        <>
          <Card className="mb-5">
            <CardBody className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="Market"><Select value={f.market} onChange={set("market")}><option value="">Both</option><option value="MARKET_A">No goal 0-5&apos;</option><option value="MARKET_B">Level at 5&apos;</option></Select></Field>
              <Field label="Min. estimated edge %" hint="Edge = estimate × odds − 1"><Input type="number" step="0.5" value={f.min_edge} onChange={set("min_edge")} placeholder="e.g. 2" /></Field>
              <Field label="Sort by"><Select value={f.sort} onChange={set("sort")}><option value="edge">Edge</option><option value="kickoff">Kick-off</option><option value="probability">Probability</option></Select></Field>
            </CardBody>
          </Card>
          {error && <Alert tone="danger" className="mb-4">{error.message}</Alert>}
          {data?.items.some((i) => i.is_demo) && <Alert tone="demo" className="mb-4" title="Demo odds">Synthetic prices derived from the model plus a margin - by construction there is no value in them.</Alert>}
          <Card>
            {loading ? <CardBody><Skeleton className="h-64" /></CardBody> : !data?.items.length ? (
              <EmptyState icon={Scale} title="No priced matches">{data?.message}</EmptyState>
            ) : (
              <>
                <Table>
                  <thead><tr><Th>Match</Th><Th>Market</Th><Th className="text-right">Estimate</Th><Th className="text-right">Fair odds</Th><Th className="text-right">Best odds</Th><Th className="text-right">Edge</Th><Th>Updated</Th><Th /></tr></thead>
                  <tbody>
                    {data.items.map((i) => (
                      <tr key={i.prediction_id} className="hover:bg-surface-2/50">
                        <Td><Link href={`/matches/${i.fixture.id}`} className="font-medium hover:text-brand-400">{i.fixture.home_team.name} vs {i.fixture.away_team.name}</Link>
                          <p className="text-xs text-subtle">{i.fixture.competition.name} · {kickoff(i.fixture.kickoff_at)} {i.is_demo && <DemoBadge />}</p></Td>
                        <Td className="whitespace-nowrap text-xs">{MARKET_LABEL[i.market]} <CategoryBadge category={i.category} /></Td>
                        <Td className="text-right"><ProbabilityValue value={i.probability} /></Td>
                        <Td className="tabular text-right text-muted">{i.fair_odds.toFixed(2)}</Td>
                        <Td className="text-right"><span className="tabular font-semibold">{i.best.decimal_odds.toFixed(2)}</span><p className="text-xs text-subtle">{i.best.bookmaker} · {i.best.n_books} book{i.best.n_books > 1 && "s"}</p></Td>
                        <Td className="text-right"><EdgeValue edge={i.edge} /></Td>
                        <Td className="whitespace-nowrap text-xs text-muted">{relative(i.best.captured_at)}</Td>
                        <Td className="text-right"><Link href={`/matches/${i.fixture.id}#odds`} className="inline-flex h-8 items-center rounded-[var(--radius-md)] border border-border-strong px-3 text-xs font-semibold hover:bg-surface-2">Compare &amp; open</Link></Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <Pager page={data.page} pages={data.pages} onPage={setPage} />
              </>
            )}
          </Card>
          <p className="mt-4 text-xs text-subtle">{data?.notice} Prices older than {data?.max_age_minutes ?? 180} minutes are ignored. Open a match to compare sportsbooks and follow an authorised link.</p>
        </>
      )}
    </>
  );
}
