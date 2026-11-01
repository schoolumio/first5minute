import type { Category, Market, Quality } from "./types";

export const MARKET_LABEL: Record<Market, string> = {
  MARKET_A: "No goal 0-5'",
  MARKET_B: "Level at 5'",
};
export const MARKET_LONG: Record<Market, string> = {
  MARKET_A: "No goal in the first five minutes (0-0 at the cutoff)",
  MARKET_B: "Scores level at the five-minute cutoff (0-0, 1-1, 2-2 ...)",
};
export const CATEGORY_LABEL: Record<Category, string> = {
  qualified: "Qualified",
  watchlist: "Watchlist",
  below_threshold: "Below threshold",
  excluded: "Excluded",
};
export const QUALITY_LABEL: Record<Quality, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  insufficient: "Insufficient",
};

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `${(v * 100).toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return v.toFixed(digits);
}

export function money(amount: number, currency = "NGN"): string {
  try {
    return new Intl.NumberFormat(currency === "NGN" ? "en-NG" : "en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toLocaleString()}`;
  }
}

export function kickoff(iso: string, opts: { date?: boolean } = { date: true }): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (opts.date === false) return time;
  return `${d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })} · ${time}`;
}

export function relative(iso: string, now: Date = new Date()): string {
  const diff = (new Date(iso).getTime() - now.getTime()) / 1000;
  const abs = Math.abs(diff);
  const units: [number, string][] = [[86400, "d"], [3600, "h"], [60, "m"]];
  for (const [secs, label] of units) {
    if (abs >= secs) {
      const v = Math.floor(abs / secs);
      return diff >= 0 ? `in ${v}${label}` : `${v}${label} ago`;
    }
  }
  return diff >= 0 ? "now" : "just now";
}

export function minSample(p: { sample_home: number; sample_away: number }): number {
  return Math.min(p.sample_home, p.sample_away);
}
