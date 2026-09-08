import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const dashboard = readFileSync(new URL("../index.html", import.meta.url), "utf-8");

describe("hitch dashboard contract", () => {
  it("exposes both Boss selectors and the advanced search entry", () => {
    expect(dashboard).toContain('id="hitchCjbCard"');
    expect(dashboard).toContain('id="hitchBossCard"');
    expect(dashboard).toContain('id="btnHitchAdvanced"');
    expect(dashboard).not.toContain('if (state.scene==="hitch") return;');
  });
});
