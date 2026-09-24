import { describe, expect, it, vi, beforeEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const htmlContent = fs.readFileSync(path.resolve(__dirname, "../index.html"), "utf-8");

function createSandbox(overrides?: (makeEl: () => any) => Record<string, unknown>) {
  const makeEl: any = () => new Proxy({}, {
    get: (target, prop) => {
      if (prop === "addEventListener") return () => {};
      if (prop === "querySelectorAll") return () => [];
      if (prop === "querySelector") return () => makeEl();
      if (prop === "dataset") return {};
      if (prop === "classList") return { add() {}, remove() {}, toggle() {} };
      if (prop === "setAttribute") return () => {};
      if (prop === "style") return {};
      return makeEl();
    },
  });

  const sandbox: Record<string, unknown> = {
    document: {
      getElementById: () => makeEl(),
      querySelectorAll: () => [],
      querySelector: () => makeEl(),
      addEventListener: () => {},
      body: makeEl(),
    },
    window: {},
    addEventListener: () => {},
    removeEventListener: () => {},
    console: { log: () => {}, error: () => {}, warn: () => {} },
    setTimeout: (fn: () => void) => fn(),
    setInterval: () => {},
    clearInterval: () => {},
    clearTimeout: () => {},
    requestAnimationFrame: (fn: () => void) => fn(),
    localStorage: { getItem: () => null, setItem: () => {} },
    matchMedia: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }),
    MutationObserver: class {
      observe() {}
      disconnect() {}
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;

  if (overrides) {
    Object.assign(sandbox, overrides(makeEl));
  }
  return sandbox;
}

describe("UI-23 Regression Tests", () => {
  describe("1. Official presets & strategy picker contract", () => {
    it("allBuilds guarantees official presets are preserved even if state.presets is corrupted", () => {
      const scriptMatch = htmlContent.match(/<script(?![^>]*src=)>([\s\S]*?)<\/script>/i);
      expect(scriptMatch).not.toBeNull();
      const script = scriptMatch![1];

      const sandbox = createSandbox();
      const context = vm.createContext(sandbox);
      vm.runInContext(script, context);

      const state = vm.runInContext("state", context) as { presets: unknown[]; custom: unknown[]; selected: string; collapsed: boolean };
      const allBuilds = vm.runInContext("allBuilds", context) as () => Array<{ id: string; name: string }>;
      const DEFAULT_PRESETS = vm.runInContext("DEFAULT_PRESETS", context) as Array<{ id: string; name: string }>;

      // Default state has 5 presets
      expect(DEFAULT_PRESETS).toHaveLength(5);
      expect(allBuilds().length).toBeGreaterThanOrEqual(5);

      // Even if state.presets is emptied, allBuilds falls back to DEFAULT_PRESETS
      state.presets = [];
      const buildsAfterWipe = allBuilds();
      expect(buildsAfterWipe.length).toBeGreaterThanOrEqual(5);
      expect(buildsAfterWipe.map((b) => b.id)).toEqual(
        expect.arrayContaining(["arcane_open", "thunder_classic", "thunder_net", "sword_qi", "aa_universal"])
      );
    });

    it("selectBuild updates state and applies official build configuration", () => {
      const scriptMatch = htmlContent.match(/<script(?![^>]*src=)>([\s\S]*?)<\/script>/i);
      const script = scriptMatch![1];

      const sandbox = createSandbox();
      const context = vm.createContext(sandbox);
      vm.runInContext(script, context);

      const state = vm.runInContext("state", context) as { selected: string; priority: string[]; collapsed: boolean };
      const selectBuild = vm.runInContext("selectBuild", context) as (id: string) => void;

      selectBuild("thunder_classic");
      expect(state.selected).toBe("thunder_classic");
      expect(state.priority).toEqual(["tl", "sdl", "asjg", "assx"]);
    });
  });

  describe("2. Special treasures collapsible grouping & 4 new attribute items", () => {
    it("NEG_GROUPS contains 4 categories and includes the 4 new items under 属性", () => {
      const scriptMatch = htmlContent.match(/<script(?![^>]*src=)>([\s\S]*?)<\/script>/i);
      const script = scriptMatch![1];
      const sandbox = createSandbox();
      const context = vm.createContext(sandbox);
      vm.runInContext(script, context);

      const groups = vm.runInContext("NEG_GROUPS", context) as Array<{ label: string; items: Array<{ name: string; effect: string }> }>;
      expect(groups).toHaveLength(4);
      expect(groups.map((g) => g.label)).toEqual(["梭哈", "资源", "属性", "战斗"]);

      const attrGroup = groups.find((g) => g.label === "属性");
      expect(attrGroup).toBeDefined();
      const attrCardNames = attrGroup!.items.map((c) => c.name);

      expect(attrCardNames).toContain("命运骰子");
      expect(attrCardNames).toContain("力之极");
      expect(attrCardNames).toContain("敏之极");
      expect(attrCardNames).toContain("智之极");

      // Verify effects match exact game text
      const dice = attrGroup!.items.find((c) => c.name === "命运骰子");
      expect(dice?.effect).toBe("50%的概率全属性增幅+25%，50%的概率全属性增幅-15%。");

      const strExtreme = attrGroup!.items.find((c) => c.name === "力之极");
      expect(strExtreme?.effect).toContain("立即扣除当前20%的敏捷与智力，将其转为力量");

      const agiExtreme = attrGroup!.items.find((c) => c.name === "敏之极");
      expect(agiExtreme?.effect).toContain("立即扣除当前20%的力量与智力，将其转为敏捷");

      const intExtreme = attrGroup!.items.find((c) => c.name === "智之极");
      expect(intExtreme?.effect).toContain("立即扣除当前20%的敏捷与力量，将其转为智力");

      // Default state does NOT contain any of the 4 items
      const state = vm.runInContext("state", context) as { negative: Set<string> };
      expect(state.negative.has("命运骰子")).toBe(false);
      expect(state.negative.has("力之极")).toBe(false);
      expect(state.negative.has("敏之极")).toBe(false);
      expect(state.negative.has("智之极")).toBe(false);
    });

    it("renderNegatives renders collapsible details with summary and fold-sum", () => {
      const scriptMatch = htmlContent.match(/<script(?![^>]*src=)>([\s\S]*?)<\/script>/i);
      const script = scriptMatch![1];

      let renderedHtml = "";
      const fakeNegativesEl: any = {
        set innerHTML(val: string) {
          renderedHtml = val;
        },
        get innerHTML() {
          return renderedHtml;
        },
        addEventListener() {},
        querySelectorAll: () => [],
        querySelector: () => null,
      };

      const sandbox = createSandbox((makeEl) => ({
        document: {
          getElementById: (id: string) => (id === "negatives" ? fakeNegativesEl : makeEl()),
          querySelectorAll: () => [],
          querySelector: () => makeEl(),
          addEventListener: () => {},
          body: makeEl(),
        },
      }));

      const context = vm.createContext(sandbox);
      vm.runInContext(script, context);

      const renderNegatives = vm.runInContext("renderNegatives", context) as () => void;
      renderNegatives();

      expect(renderedHtml).toContain('<details class="neg-fold" data-fold="neg_0"');
      expect(renderedHtml).toContain('<details class="neg-fold" data-fold="neg_2"');
      expect(renderedHtml).toContain('<details class="neg-fold" data-fold="neg_2" open>');
      expect(renderedHtml).toContain('<summary class="neg-group">');
      expect(renderedHtml).toContain('<span class="fold-sum">默认不拿</span>');
      expect(renderedHtml).toContain('data-neg="命运骰子"');
      expect(renderedHtml).toContain('data-neg="力之极"');
      expect(renderedHtml).toContain('data-neg="敏之极"');
      expect(renderedHtml).toContain('data-neg="智之极"');
      expect(renderedHtml).toContain('aria-label="放行命运骰子"');
    });
  });

  describe("3. Hitch goal ending option (hitch_after_goal = end)", () => {
    it("index.html contains 结束脚本 button with data-value=end in hitch-after-goal group", () => {
      expect(htmlContent).toContain('data-od-id="hitch-after-goal"');
      expect(htmlContent).toMatch(/data-team-rule=["']afterGoal["']\s+data-value=["']end["']/);
      expect(htmlContent).toContain("结束脚本");
    });

    it("removes legacy __SB_ALLOW_STOP_AFTER__ feature flag block", () => {
      expect(htmlContent).not.toContain("__SB_ALLOW_STOP_AFTER__");
    });
  });

  describe("4. Layout & anti-overlap CSS rules", () => {
    it("keeps skill and treasure above a full-width bond panel", () => {
      expect(htmlContent).toContain("#farmBody .main-workspace > .sb-treasure");
      expect(htmlContent).toMatch(/\.main-workspace > \[data-od-id="skill-panel"\] \{[^}]*grid-column: 1 !important;[^}]*grid-row: 1 !important;/);
      expect(htmlContent).toMatch(/\.main-workspace > \.sb-treasure \{[^}]*grid-column: 2 !important;[^}]*grid-row: 1 !important;/);
      expect(htmlContent).toMatch(/\.main-workspace > \.bond-config \{[^}]*grid-column: 1 \/ -1 !important;[^}]*grid-row: 2 !important;/);
      expect(htmlContent).toMatch(/\.sb-treasure \.sb-treasure-body \{[^}]*flex: 0 0 auto !important;[^}]*overflow: visible !important;/);
      expect(htmlContent).toContain('#farmBody.sb-bond-editing [data-od-id="skill-panel"] > :not(.skill-head)');
    });

    it("places base and advanced bond decks in two equal columns", () => {
      expect(htmlContent).toMatch(/#farmBody #bonds:not\(:has\(\.chips\)\) \{[^}]*display: grid !important;[^}]*grid-template-columns: minmax\(0, 1fr\) minmax\(260px, 1fr\) !important;/);
      expect(htmlContent).toContain("gap: 12px 18px !important;");
    });

    it("keeps the dragonball control in treasure settings and gives the log an opaque surface", () => {
      expect(htmlContent).toContain('if (heading?.tagName === "H4" && /龙珠/.test(heading.textContent)) heading.remove();');
      expect(htmlContent).toContain('panel.appendChild(dragonRow);');
      expect(htmlContent).toContain("background: #f8f9fb;");
      expect(htmlContent).toContain("body[data-theme=\"dark\"] .sb-logstrip { background: #252a32; }");
      expect(htmlContent).toContain('window.addEventListener("blur", closeLog);');
      expect(htmlContent).toContain(".drawer { height: fit-content;");
    });

    it("closes the log when clicking the board or leaving the app, but not inside the log", () => {
      const start = htmlContent.indexOf("/* ===== 补丁 U · 二级窗口互斥");
      const end = htmlContent.indexOf("/* ===== 补丁 V 脚本", start);
      expect(start).toBeGreaterThan(0);
      expect(end).toBeGreaterThan(start);

      let open = true;
      let expanded = "true";
      const handlers: Record<string, (event?: any) => void> = {};
      const strip = {
        classList: { contains: (name: string) => name === "open" && open, remove: () => { open = false; } },
        contains: (target: string) => target === "inside",
      };
      const button = {
        contains: (target: string) => target === "toggle",
        setAttribute: (_name: string, value: string) => { expanded = value; },
      };
      vm.runInNewContext(htmlContent.slice(start, end), {
        document: {
          getElementById: (id: string) => ({ sbLogStrip: strip, sbLogToggle: button } as any)[id] || null,
          addEventListener: (name: string, handler: (event?: any) => void) => { handlers[name] = handler; },
        },
        window: { addEventListener: (name: string, handler: () => void) => { handlers[name] = handler; } },
        MutationObserver: class { observe() {} },
        setTimeout: () => {},
      });

      handlers.pointerdown({ target: "inside" });
      expect(open).toBe(true);
      handlers.pointerdown({ target: "toggle" });
      expect(open).toBe(true);
      handlers.pointerdown({ target: "board" });
      expect(open).toBe(false);
      expect(expanded).toBe("false");
      open = true;
      handlers.blur();
      expect(open).toBe(false);
    });

    it("respects prefers-reduced-motion with global override", () => {
      expect(htmlContent).toContain("@media (prefers-reduced-motion: reduce)");
      expect(htmlContent).toContain("animation-duration: 0.001ms !important;");
      expect(htmlContent).toContain("transition-duration: 0.001ms !important;");
    });
  });

  describe("5. Brand & version formatting", () => {
    it("formats brand to v0.3 · UI-23", () => {
      expect(htmlContent).toContain('id="versionLabel" title="构建身份：待预检">v0.3 · UI-23</span>');
      expect(htmlContent).toContain('class="brand-sep" aria-hidden="true">·</span>');
    });

    it("UI_BUILD constant in script is set to UI-23", () => {
      expect(htmlContent).toContain('const UI_BUILD = "UI-23";');
      expect(htmlContent).not.toContain('const UI_BUILD = "UI-22";');
    });
  });

  describe("5a. End-of-run and activation motion", () => {
    it("renders hitch and solo evidence in one completion card without inventing stages", () => {
      const source = htmlContent.match(/function runBreakdown\(summary, modeId\) \{[\s\S]*?\n      \}/);
      expect(source).not.toBeNull();
      const format = vm.runInNewContext(`${source![0]}; runBreakdown`, {
        esc: (value: string) => value.replace(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char]!)),
      }) as (summary: unknown, modeId: string) => string;
      const card = format({ available: true, duration_seconds: 125, hitch: { started: 3, completed: 3, success: 2, failure: 1, stages: { "2-1": 2, "2-3": 1 } }, solo: { completed: 2, success: 1, failure: 1 } }, "lobby_hitch");
      expect(card).toContain("蹭车统计");
      expect(card).toContain("单人模式统计");
      expect(card).toContain("2-1 · 2 把");
      expect(card).toContain("2-3 · 1 把");
      expect(format({ available: false }, "lobby_hitch")).toContain("未取得可核对的战绩明细");
    });

    it("keeps activation particles bounded and disables motion when requested", () => {
      expect(htmlContent).toContain("const dust = reduce() ? \"\" : Array.from({ length: 22 }");
      expect(htmlContent).toContain("if (!reduce()) setTimeout(() => surgeLiquidRainbow(3600), 250);");
      expect(htmlContent).toContain(".sb-act.in .sb-act-dust i");
      expect(htmlContent).toContain(".sb-act-dust, .sb-act-wave { display: none; }");
      expect(htmlContent).toContain(".sb-done-sparks { display: none; }");
    });
  });

  describe("6. Bridge patch wiring contract", () => {
    it("keeps the launch preview visible through STARTING and closes it on RUNNING", () => {
      const bridgeSource = fs.readFileSync(path.resolve(__dirname, "../src/main.ts"), "utf-8");
      expect(bridgeSource).toContain("state.runState = run.state;");
      const wrapper = htmlContent.match(/window\.renderHud = function \(\) \{ hud2\(\); if \(state\.runState === "RUNNING" && \["MAIN_LINE"[^\n]+\.includes\(state\.hudPhase\) && pre\) preflightStage\("running"\); \};/);
      expect(wrapper).not.toBeNull();
      const stages: string[] = [];
      const sandbox = { window: {} as { renderHud?: () => void }, state: { runState: "RUNNING", hudPhase: "STARTING" }, pre: {}, hud2: () => {}, preflightStage: (stage: string) => stages.push(stage) };
      vm.runInNewContext(wrapper![0], sandbox);
      sandbox.window.renderHud?.();
      expect(stages).toEqual([]);
      sandbox.state.hudPhase = "LOBBY_ROOM";
      sandbox.window.renderHud?.();
      expect(stages).toEqual([]);
      sandbox.state.hudPhase = "MAIN_LINE";
      sandbox.window.renderHud?.();
      expect(stages).toEqual(["running"]);
    });

    it("queues hitch_after_goal: end properly via config queue", async () => {
      const { enqueueConfigPatch, resetStickyFailure, setSettingsRevision } = await import("../src/config_queue");
      resetStickyFailure();
      setSettingsRevision(1);

      let sentPatch: any = null;
      const mockBridge = {
        update_config: vi.fn(async (patch: any) => {
          sentPatch = patch;
          return {
            ok: true,
            request_id: patch.request_id,
            settings_revision: 2,
            snapshot_seq: 1,
            errors: [],
            settings: {},
            strategy: {},
          };
        }),
      };

      await enqueueConfigPatch({ hitch_after_goal: "end" }, mockBridge as any);
      expect(sentPatch).not.toBeNull();
      expect(sentPatch.hitch_after_goal).toBe("end");
    });

    it("queues treasure negative allowlist via both settings and strategy", async () => {
      const { enqueueConfigPatch, resetStickyFailure, setSettingsRevision } = await import("../src/config_queue");
      resetStickyFailure();
      setSettingsRevision(2);

      let sentPatch: any = null;
      const mockBridge = {
        update_config: vi.fn(async (patch: any) => {
          sentPatch = patch;
          return {
            ok: true,
            request_id: patch.request_id,
            settings_revision: 3,
            snapshot_seq: 2,
            errors: [],
            settings: {},
            strategy: {},
          };
        }),
      };

      const negatives = ["命运骰子", "力之极", "敏之极", "智之极"];
      await enqueueConfigPatch({
        treasure_allow_negative: negatives,
        strategy: {
          treasure: { negative_allowlist: negatives },
        },
      }, mockBridge as any);

      expect(sentPatch.treasure_allow_negative).toEqual(negatives);
      expect(sentPatch.strategy?.treasure?.negative_allowlist).toEqual(negatives);
    });

    it("queues regular switches and reputation toggle via bridge", async () => {
      const { enqueueConfigPatch, resetStickyFailure, setSettingsRevision } = await import("../src/config_queue");
      resetStickyFailure();
      setSettingsRevision(3);

      const sentPatches: any[] = [];
      const mockBridge = {
        update_config: vi.fn(async (patch: any) => {
          sentPatches.push(patch);
          return {
            ok: true,
            request_id: patch.request_id,
            settings_revision: patch.settings_revision + 1,
            snapshot_seq: 1,
            errors: [],
            settings: {},
            strategy: {},
          };
        }),
      };

      await enqueueConfigPatch({ auto_secret_realm: false }, mockBridge as any);
      await enqueueConfigPatch({ auto_close_main_line: false }, mockBridge as any);
      await enqueueConfigPatch({ auto_archaeology: false }, mockBridge as any);
      await enqueueConfigPatch({ new_room_every_times: true }, mockBridge as any);
      await enqueueConfigPatch({ find_longzhu_where_multi_game: true }, mockBridge as any);
      await enqueueConfigPatch({ auto_reputation: false, reputation_allocations: {} }, mockBridge as any);

      expect(sentPatches[0].auto_secret_realm).toBe(false);
      expect(sentPatches[1].auto_close_main_line).toBe(false);
      expect(sentPatches[2].auto_archaeology).toBe(false);
      expect(sentPatches[3].new_room_every_times).toBe(true);
      expect(sentPatches[4].find_longzhu_where_multi_game).toBe(true);
      expect(sentPatches[5].auto_reputation).toBe(false);
    });
  });
});
