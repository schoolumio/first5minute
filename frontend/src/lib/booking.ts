/** Small, pure helpers for the Booking Code Converter UI (unit-tested). */
import { MARKET_LONG } from "./format";
import type { ConversionSelection, ConversionStatus } from "./types";
import type { TicketItem } from "./ticket";

export const STATUS_LABEL: Record<ConversionStatus, string> = {
  pending: "Waiting",
  matched: "Matched",
  odds_changed: "Odds changed",
  unmatched: "Unmatched",
  unavailable: "Unavailable",
};

export function isConverted(s: Pick<ConversionSelection, "status">): boolean {
  return s.status === "matched" || s.status === "odds_changed";
}

/** "1.90" -> "1.85": direction word for screen readers and badges. */
export function oddsChangeText(o: ConversionSelection["odds"]): string | null {
  if (!o.original || !o.destination || !o.change || o.change === "same") return null;
  return `${o.original} → ${o.destination} (${o.change === "up" ? "higher" : "lower"})`;
}

/** Normalise what a user types or pastes: remove spaces, upper case. The server validates the real format. */
export function cleanCode(raw: string): string {
  return raw.replace(/\s+/g, "").toUpperCase();
}

/** Copy to the clipboard, falling back to a hidden textarea for older mobile browsers. Resolves false if both fail. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    if (typeof document === "undefined") return false;
    const el = document.createElement("textarea");
    el.value = text;
    el.setAttribute("readonly", "");
    el.style.position = "fixed";
    el.style.opacity = "0";
    document.body.appendChild(el);
    el.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    return ok;
  } catch {
    return false;
  }
}

export interface TicketTextOptions {
  /** latest analysis per prediction id (from the ticket preview); picks marked unavailable are left out */
  preview?: Record<number, { probability?: number; fair_odds?: number | null; available?: boolean } | undefined>;
  timeZone?: string;
  locale?: string;
}

/**
 * The ticket as plain text a player can paste into a chat or read while rebuilding the slip by hand on any bookmaker.
 * Contains only what we know: games, the five-minute pick, the model's estimate and its fair odds. No bookmaker prices, no codes.
 */
export function ticketAsText(items: TicketItem[], opts: TicketTextOptions = {}): string {
  const usable = items.filter((i) => opts.preview?.[i.prediction_id]?.available !== false);
  const skipped = items.length - usable.length;
  const fmt = new Intl.DateTimeFormat(opts.locale ?? "en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: opts.timeZone });
  const lines: string[] = [`First5Minute ticket - ${usable.length} ${usable.length === 1 ? "game" : "games"}${usable.some((i) => i.is_demo) ? " (DEMO DATA, not real games)" : ""}`, ""];
  let all = 1;
  usable.forEach((i, n) => {
    const p = opts.preview?.[i.prediction_id]?.probability ?? i.probability;
    const fair = opts.preview?.[i.prediction_id]?.fair_odds ?? (p > 0 ? Math.round((1 / p) * 100) / 100 : null);
    all *= p;
    lines.push(`${n + 1}. ${i.home} vs ${i.away}`);
    lines.push(`   ${i.competition} - ${fmt.format(new Date(i.kickoff_at))}`);
    lines.push(`   Pick: ${MARKET_LONG[i.market]}`);
    lines.push(`   Model estimate: ${(p * 100).toFixed(1)}%${fair ? ` (fair odds ${fair.toFixed(2)})` : ""}`);
    lines.push("");
  });
  if (usable.length > 1) lines.push(`Chance all win (model, assumes the games are independent): ${(all * 100).toFixed(1)}%`, "");
  if (skipped) lines.push(`${skipped} ${skipped === 1 ? "pick was" : "picks were"} left out because it can no longer be used.`, "");
  lines.push("Model estimates, not guarantees. Bookmakers define and settle the first five minutes differently: read the market rules on your bookmaker before you bet. 18+. Bet responsibly.");
  return lines.join("\n");
}
