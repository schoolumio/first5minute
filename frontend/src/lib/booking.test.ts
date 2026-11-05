import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanCode, copyText, isConverted, oddsChangeText } from "./booking";

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
