/** Small, pure helpers for the Booking Code Converter UI (unit-tested). */
import type { ConversionSelection, ConversionStatus } from "./types";

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
