import { describe, expect, it } from "vitest";
import { buildQuery } from "./api";
import { minSample, pct, relative } from "./format";

describe("format helpers", () => {
  it("formats percentages and handles missing values", () => {
    expect(pct(0.8771)).toBe("87.7%");
    expect(pct(null)).toBe("-");
  });
  it("formats relative times", () => {
    const now = new Date("2026-11-01T12:00:00Z");
    expect(relative("2026-11-01T15:00:00Z", now)).toBe("in 3h");
    expect(relative("2026-10-30T12:00:00Z", now)).toBe("2d ago");
  });
  it("takes the smaller team sample", () => {
    expect(minSample({ sample_home: 12, sample_away: 7 })).toBe(7);
  });
});

describe("buildQuery", () => {
  it("skips empty values and repeats arrays", () => {
    expect(buildQuery({ a: 1, b: "", c: null, d: ["x", "y"], e: false })).toBe("?a=1&d=x&d=y&e=false");
    expect(buildQuery()).toBe("");
  });
});
