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

  it("escapes user search terms and backend subscription text in the launch summary", () => {
    // 摘要用 innerHTML 渲染，页面可调用 QWebChannel facade：用户/后端字符串必须转义。
    expect(dashboard).toContain("esc(window.hitchSearchTerms.terms ? window.hitchSearchTerms.terms.join(\",\")");
    expect(dashboard).toContain('esc(state.subscription.status || "未激活")');
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

  it("displays fallback hint text on hitch, follow, and solo boss configuration sections", () => {
    const hint = "找不到时：按顺序定位，仍找不到就选能点到的最后一个";
    const matches = dashboard.match(new RegExp(hint, "g"));
    expect(matches).not.toBeNull();
    expect(matches!.length).toBe(3);
  });

  it("sorts modal boss stems by numeric prefix", () => {
    expect(dashboard).toContain("const parseNo = (s) => parseInt(String(s).match(/^\\d+/)?.[0] || \"999\", 10);");
    expect(dashboard).toContain(".sort((a, b) => parseNo(a) - parseNo(b))");
  });
});
