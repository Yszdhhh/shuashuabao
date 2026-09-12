import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { parseHitchSearchTerms } from "../src/main";

const dashboard = readFileSync(new URL("../index.html", import.meta.url), "utf-8");

describe("hitch dashboard contract", () => {
  it("exposes both Boss selectors and the advanced search entry", () => {
    expect(dashboard).toContain('id="hitchCjbCard"');
    expect(dashboard).toContain('id="hitchBossCard"');
    expect(dashboard).toContain('id="btnHitchAdvanced"');
    expect(dashboard).not.toContain('if (state.scene==="hitch") return;');
  });

  it("exposes hitchSearchCard and hitchSearchSummary in hitch console", () => {
    expect(dashboard).toContain('id="hitchSearchCard"');
    expect(dashboard).toContain('id="hitchSearchSummary"');
  });

  it("removes sandbox toast for btnHitchAdvanced", () => {
    expect(dashboard).not.toContain('高级搜房：沙盒仅展示入口');
  });

  it("parseHitchSearchTerms preserves three and more terms including Chinese", () => {
    const result3 = parseHitchSearchTerms("4,3,速");
    expect(result3.terms).toEqual(["4", "3", "速"]);
    expect(result3.primary).toBe("4");
    expect(result3.secondary).toBe("3");

    const result5 = parseHitchSearchTerms("4, 3, 速, 刷, 秘境");
    expect(result5.terms).toEqual(["4", "3", "速", "刷", "秘境"]);
    expect(result5.terms.join(",")).toBe("4,3,速,刷,秘境");

    // Full-width Chinese comma support
    const resultFullWidth = parseHitchSearchTerms("4，3，速");
    expect(resultFullWidth.terms).toEqual(["4", "3", "速"]);

    // Deduplication while preserving order
    const resultDedup = parseHitchSearchTerms("4, 3, 速, 4, 刷, 速");
    expect(resultDedup.terms).toEqual(["4", "3", "速", "刷"]);

    // Fallback on empty
    const resultEmpty = parseHitchSearchTerms("");
    expect(resultEmpty.terms).toEqual(["4", "3", "速"]);
  });
});
