"use client";

/**
 * Chart components. Palette validated with the dataviz validator against the
 * dark surface #0b1424: series 1 (home) #55a11f, series 2 (away) #3b82f6.
 * Thin marks, rounded data-ends, recessive grid, hover tooltips, legend for
 * >= 2 series, text in text tokens (never series colours).
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  ReferenceLine,
  ComposedChart,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export const SERIES = { home: "#55a11f", away: "#3b82f6" } as const;
const AXIS = { stroke: "#64748b", fontSize: 11, tickLine: false, axisLine: false } as const;
const GRID = { stroke: "#1e2d47", strokeDasharray: "0", vertical: false } as const;

function TooltipBox({ active, payload, label, fmt }: {
  active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string; fmt?: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-[var(--radius-md)] border border-border-strong bg-surface-2 px-3 py-2 text-xs shadow-xl">
      <p className="mb-1 font-semibold text-fg">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-2 text-muted">
          <span className="h-2 w-2 rounded-sm" style={{ background: p.color }} />
          {p.name}: <span className="tabular font-semibold text-fg">{fmt ? fmt(p.value) : p.value}</span>
        </p>
      ))}
    </div>
  );
}

/** First-goal timing distribution for home and away team (counts of matches). */
export function TimingChart({ home, away, homeName, awayName }: {
  home: { bucket: string; count: number }[]; away: { bucket: string; count: number }[]; homeName: string; awayName: string;
}) {
  const data = home.map((h, i) => ({ bucket: h.bucket === "no_goal" ? "No goal" : h.bucket, [homeName]: h.count, [awayName]: away[i]?.count ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }} barGap={2} barCategoryGap="22%">
        <CartesianGrid {...GRID} />
        <XAxis dataKey="bucket" {...AXIS} />
        <YAxis allowDecimals={false} {...AXIS} />
        <Tooltip cursor={{ fill: "rgb(255 255 255 / 0.04)" }} content={<TooltipBox fmt={(v) => `${v} matches`} />} />
        <Legend wrapperStyle={{ fontSize: 12, color: "#94a3b8" }} iconType="square" iconSize={8} />
        <Bar dataKey={homeName} fill={SERIES.home} radius={[4, 4, 0, 0]} maxBarSize={18} />
        <Bar dataKey={awayName} fill={SERIES.away} radius={[4, 4, 0, 0]} maxBarSize={18} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Home vs away rates for a set of metrics (values are proportions 0-1). */
export function ComparisonChart({ rows, homeName, awayName }: {
  rows: { metric: string; home: number | null; away: number | null }[]; homeName: string; awayName: string;
}) {
  const data = rows.map((r) => ({ metric: r.metric, [homeName]: r.home ?? 0, [awayName]: r.away ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -10, bottom: 0 }} barGap={2} barCategoryGap="28%">
        <CartesianGrid {...GRID} />
        <XAxis dataKey="metric" {...AXIS} interval={0} />
        <YAxis {...AXIS} tickFormatter={(v) => `${Math.round(v * 100)}%`} domain={[0, 1]} />
        <Tooltip cursor={{ fill: "rgb(255 255 255 / 0.04)" }} content={<TooltipBox fmt={(v) => `${(v * 100).toFixed(1)}%`} />} />
        <Legend wrapperStyle={{ fontSize: 12, color: "#94a3b8" }} iconType="square" iconSize={8} />
        <Bar dataKey={homeName} fill={SERIES.home} radius={[4, 4, 0, 0]} maxBarSize={22} />
        <Bar dataKey={awayName} fill={SERIES.away} radius={[4, 4, 0, 0]} maxBarSize={22} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Reliability diagram: mean predicted vs observed frequency per bin, with the perfect-calibration diagonal. */
export function CalibrationChart({ bins }: {
  bins: { mean_predicted: number; observed_rate: number; count: number }[];
}) {
  const lo = Math.min(0.6, ...bins.map((b) => Math.min(b.mean_predicted, b.observed_rate))) - 0.02;
  const domain: [number, number] = [Math.max(0, Math.floor(lo * 20) / 20), 1];
  const data = bins.map((b) => ({ x: b.mean_predicted, observed: b.observed_rate, count: b.count }));
  const diag = [{ x: domain[0], ideal: domain[0] }, { x: 1, ideal: 1 }];
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart margin={{ top: 8, right: 12, left: -10, bottom: 4 }}>
        <CartesianGrid stroke="#1e2d47" />
        <XAxis type="number" dataKey="x" domain={domain} {...AXIS} tickFormatter={(v) => `${Math.round(v * 100)}%`}
          label={{ value: "Predicted", position: "insideBottom", offset: -2, fill: "#64748b", fontSize: 11 }} />
        <YAxis type="number" domain={domain} {...AXIS} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
        <Tooltip
          content={({ active, payload }) => {
            const p = payload?.find((x) => x.dataKey === "observed")?.payload as { x: number; observed: number; count: number } | undefined;
            if (!active || !p) return null;
            return (
              <div className="rounded-[var(--radius-md)] border border-border-strong bg-surface-2 px-3 py-2 text-xs shadow-xl">
                <p className="text-muted">Predicted <span className="tabular font-semibold text-fg">{(p.x * 100).toFixed(1)}%</span></p>
                <p className="text-muted">Observed <span className="tabular font-semibold text-fg">{(p.observed * 100).toFixed(1)}%</span></p>
                <p className="text-muted">Predictions <span className="tabular font-semibold text-fg">{p.count}</span></p>
              </div>
            );
          }}
        />
        <Line data={diag} dataKey="ideal" stroke="#64748b" strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} legendType="none" />
        <Scatter data={data} dataKey="observed" fill={SERIES.home} stroke="#0b1424" strokeWidth={2} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export interface TrendPoint { period: string; n: number; hit_rate: number; mean_predicted: number; brier: number | null }

/** Observed hit rate vs mean model estimate per period (same unit, one axis). Dots carry the per-period sample size in the tooltip. */
export function TrendChart({ points }: { points: TrendPoint[] }) {
  const data = points.map((p) => ({ ...p, label: new Date(p.period).toLocaleDateString(undefined, { day: "numeric", month: "short" }) }));
  const lo = Math.max(0, Math.floor((Math.min(...points.map((p) => Math.min(p.hit_rate, p.mean_predicted))) - 0.03) * 20) / 20);
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, left: -10, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="label" {...AXIS} />
        <YAxis {...AXIS} domain={[lo, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
        <Tooltip
          cursor={{ stroke: "#2a3d5c" }}
          content={({ active, payload }) => {
            const d = payload?.[0]?.payload as (TrendPoint & { label: string }) | undefined;
            if (!active || !d) return null;
            return (
              <div className="rounded-[var(--radius-md)] border border-border-strong bg-surface-2 px-3 py-2 text-xs shadow-xl">
                <p className="mb-1 font-semibold text-fg">Week of {d.label}</p>
                <p className="text-muted">Model estimate <span className="tabular font-semibold text-fg">{(d.mean_predicted * 100).toFixed(1)}%</span></p>
                <p className="text-muted">Observed hit rate <span className="tabular font-semibold text-fg">{(d.hit_rate * 100).toFixed(1)}%</span></p>
                <p className="text-muted">Settled predictions <span className="tabular font-semibold text-fg">{d.n}</span></p>
              </div>
            );
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12, color: "#94a3b8" }} iconType="plainline" />
        <Line name="Model estimate" dataKey="mean_predicted" stroke={SERIES.home} strokeWidth={2} dot={{ r: 4, fill: SERIES.home, stroke: "#0b1424", strokeWidth: 2 }} isAnimationActive={false} />
        <Line name="Observed hit rate" dataKey="hit_rate" stroke={SERIES.away} strokeWidth={2} dot={{ r: 4, fill: SERIES.away, stroke: "#0b1424", strokeWidth: 2 }} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Best available decimal odds over time vs the model's fair odds (1 / probability). Edge exists only where the line is above the dashed one. */
export function OddsHistoryChart({ points, fair }: { points: { t: string; best: number | null }[]; fair: number | null }) {
  const data = points.map((p) => ({ ...p, label: new Date(p.t).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) }));
  const vals = [...points.map((p) => p.best).filter((v): v is number => v !== null), ...(fair ? [fair] : [])];
  const lo = Math.max(1, Math.floor((Math.min(...vals) - 0.02) * 50) / 50), hi = Math.ceil((Math.max(...vals) + 0.02) * 50) / 50;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, left: -10, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="label" {...AXIS} minTickGap={48} />
        <YAxis {...AXIS} domain={[lo, hi]} tickFormatter={(v) => v.toFixed(2)} />
        <Tooltip cursor={{ stroke: "#2a3d5c" }} content={<TooltipBox fmt={(v) => v.toFixed(2)} />} />
        {fair && <ReferenceLine y={fair} stroke="#94a3b8" strokeDasharray="5 4" label={{ value: `Model fair odds ${fair.toFixed(2)}`, fill: "#94a3b8", fontSize: 11, position: "insideTopRight" }} />}
        <Line name="Best available odds" dataKey="best" type="stepAfter" stroke={SERIES.away} strokeWidth={2} dot={{ r: 3, fill: SERIES.away, stroke: "#0b1424", strokeWidth: 2 }} isAnimationActive={false} connectNulls />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
