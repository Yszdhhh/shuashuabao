import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const dashboard = readFileSync(new URL("../index.html", import.meta.url), "utf-8");

describe("official solo deck defaults", () => {
  it("offers 提速 and 体术 in the basic-card editor", () => {
    expect(dashboard).toContain('"提速","体术"');
  });

  it("includes 祝福 in every official preset", () => {
    const start = dashboard.indexOf("const DEFAULT_PRESETS =");
    const end = dashboard.indexOf("const BUILDS", start);
    expect(start).toBeGreaterThanOrEqual(0);
    expect(end).toBeGreaterThan(start);
    const presets = [...dashboard.slice(start, end).matchAll(/growth:\[([^\]]*)\]/g)];
    expect(presets).toHaveLength(5);
    expect(presets.every((preset) => preset[1].includes('"祝福"'))).toBe(true);
  });
});
