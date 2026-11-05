import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanCode, copyText, isConverted, oddsChangeText, ticketAsText } from "./booking";

describe("booking converter helpers", () => {
  it("cleans pasted codes", () => {
    expect(cleanCode(" ab c 12\n3 ")).toBe("ABC123");
  });
  it("knows which statuses count as converted", () => {
    expect(isConverted({ status: "matched" })).toBe(true);
    expect(isConverted({ status: "odds_changed" })).toBe(true);
    for (const s of ["unmatched", "unavailable", "pending"] as const) expect(isConverted({ status: s })).toBe(false);
  });
  it("describes odds changes only when they changed", () => {
    expect(oddsChangeText({ original: "1.90", destination: "1.85", change: "down" })).toBe("1.90 → 1.85 (lower)");
    expect(oddsChangeText({ original: "1.80", destination: "1.90", change: "up" })).toBe("1.80 → 1.90 (higher)");
    expect(oddsChangeText({ original: "1.90", destination: "1.90", change: "same" })).toBeNull();
    expect(oddsChangeText({ original: null, destination: null, change: null })).toBeNull();
  });
});

describe("copyText", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the async clipboard when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    expect(await copyText("DEMO-1234")).toBe(true);
    expect(writeText).toHaveBeenCalledWith("DEMO-1234");
  });

  it("falls back to execCommand when the clipboard API fails", async () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    const el = { value: "", setAttribute: vi.fn(), style: {} as Record<string, string>, select: vi.fn() };
    const body = { appendChild: vi.fn(), removeChild: vi.fn() };
    vi.stubGlobal("document", { createElement: () => el, body, execCommand: vi.fn().mockReturnValue(true) });
    expect(await copyText("ABC")).toBe(true);
    expect(el.value).toBe("ABC");
    expect(body.removeChild).toHaveBeenCalled();
  });

  it("reports failure instead of pretending it copied", async () => {
    vi.stubGlobal("navigator", {});
    vi.stubGlobal("document", undefined);
    expect(await copyText("ABC")).toBe(false);
  });
});

describe("ticketAsText", () => {
  const item = (id: number, over: Partial<import("./ticket").TicketItem> = {}): import("./ticket").TicketItem => ({
    prediction_id: id, fixture_id: id, market: "MARKET_A", home: "Alpha FC", away: "Beta United", competition: "Premier Division",
    kickoff_at: "2026-11-07T19:00:00Z", probability: 0.9, category: "qualified", is_demo: false, ...over,
  });
  it("lists games, the pick, the estimate and the disclaimer, with no bookmaker prices or codes", () => {
    const t = ticketAsText([item(1), item(2, { market: "MARKET_B", home: "Gamma", away: "Delta", probability: 0.8 })], { timeZone: "UTC" });
    expect(t).toContain("2 games");
    expect(t).toContain("1. Alpha FC vs Beta United");
    expect(t).toContain("No goal in the first five minutes");
    expect(t).toContain("Scores level at the five-minute cutoff");
    expect(t).toContain("Model estimate: 90.0% (fair odds 1.11)");
    expect(t).toContain("Chance all win (model, assumes the games are independent): 72.0%");
    expect(t).toContain("not guarantees");
    expect(t).not.toMatch(/booking code|DEMO-/i);
  });
  it("prefers the latest analysis, leaves out unusable picks and labels demo data", () => {
    const t = ticketAsText([item(1, { is_demo: true }), item(2)], { timeZone: "UTC", preview: { 1: { probability: 0.95, fair_odds: 1.05 }, 2: { available: false } } });
    expect(t).toContain("1 game (DEMO DATA");
    expect(t).toContain("95.0% (fair odds 1.05)");
    expect(t).toContain("1 pick was left out");
    expect(t).not.toContain("Chance all win");
  });
});
