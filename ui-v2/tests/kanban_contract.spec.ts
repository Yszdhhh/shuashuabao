import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

/**
 * 刷刷宝 UI-V2 看板架构契约测试
 * 
 * 保证 index.html (经典内联脚本与 DOM) 与 src/main.ts (I/O 适配层) 的接口契约双向对齐。
 * 覆盖：全局函数、全局常量、DOM ID、SWITCHES、data-* 选择器、state 结构。
 */

export const CONTRACT = {
  // main.ts 直接通过 $(id) / getElementById(id) / #id 依赖的静态 DOM 节点
  STATIC_DOM_IDS: [
    // 宿主与身份
    "scene-app",
    "versionLabel",
    "subscriptionPill",
    "evidencePill",
    "identityPill",
    "statusPill",
    "btnMin",
    "btnClose",
    "btnTheme",
    // 运行态与仪表盘
    "gamesToday",
    "gamesCap",
    "lamp",
    "lampText",
    "startErr",
    "btnStart",
    "loadBar",
    "btnActivateKey",
    // 策略与配置卡片
    "skillRank",
    "bonds",
    "negatives",
    "downgradeAfterFailures",
    // 房间与组队（注：用户已拍板确认跟车业务无配对码设计，移除 followPairForm / followPairCode）
    "roomName",
    "roomPass",
    "btnHitchAdvanced",
    // 抽屉开关
    "swSecret",
    "swCloseML",
    "swAutoArch",
    "swNewRoom",
    "swDragon",
    // 模态弹窗层
    "modalLayer",
    "modalSheet",
  ] as const,

  // 由模板/函数动态写入 innerHTML 的元素 ID 与 data 标记
  DYNAMIC_SIGNATURES: [
    "btnSaveBonds",
    "subscriptionKey",
    "data-stem",
    "data-apply-rep",
    "data-close",
    "data-activate-subscription",
  ] as const,

  // main.ts 依赖的经典脚本全局函数（declare function 与 afterGlobalCall）
  GLOBAL_FUNCTIONS: [
    "$",
    "toast",
    "setSwitch",
    "setScene",
    "setCycle",
    "refreshSummary",
    "renderChapterStage",
    "renderBuilds",
    "renderBonds",
    "renderNegatives",
    "renderPrestige",
    "renderTeamRules",
    "renderNames",
    "currentSkills",
    "applyOfficial",
    "renderSkillRank",
    "renderWizard",
  ] as const,

  // main.ts 依赖的全局常量
  GLOBAL_CONSTANTS: [
    "state",
    "BUILDS",
    "FACTIONS",
    "STAGE_MAX",
  ] as const,

  // 抽屉开关表（main.ts SWITCHES）
  SWITCHES: [
    { el: "swSecret", stateKey: "autoSecret", field: "auto_secret_realm" },
    { el: "swCloseML", stateKey: "closeMainline", field: "auto_close_main_line" },
    { el: "swAutoArch", stateKey: "autoArch", field: "auto_archaeology" },
    { el: "swNewRoom", stateKey: "newRoom", field: "new_room_every_times" },
    { el: "swDragon", stateKey: "dragonPrefer", field: "find_longzhu_where_multi_game" },
  ] as const,

  // DOM 事件绑定的 data-* 选择器
  DATA_SELECTORS: [
    "data-team-rules",
    "data-team-cycle-input",
    "data-team-cycle-step",
    "data-team-rule",
    "data-adv-move",
    "data-adv-pick",
    "data-route",
  ] as const,

  // main.ts 读取或写入的核心 state 字段
  STATE_FIELDS: [
    "scene",
    "cycle",
    "chapter",
    "stage",
    "priority",
    "alloc",
    "hero",
    "teamRules",
    "selected",
    "custom",
    "collapsed",
    "routes",
    "cjb",
    "boss",
  ] as const,
};

/**
 * 契约合规性审计器：解析给定 HTML 字符串并比对契约要求
 */
export function auditKanbanContract(htmlContent: string) {
  const missingStaticIds: string[] = [];
  const missingDynamicSignatures: string[] = [];
  const missingDataSelectors: string[] = [];
  const missingSwitches: string[] = [];

  for (const id of CONTRACT.STATIC_DOM_IDS) {
    const idPattern = new RegExp(`id=["']${id}["']`, "i");
    if (!idPattern.test(htmlContent)) {
      missingStaticIds.push(id);
    }
  }

  for (const sig of CONTRACT.DYNAMIC_SIGNATURES) {
    if (!htmlContent.includes(sig)) {
      missingDynamicSignatures.push(sig);
    }
  }

  for (const attr of CONTRACT.DATA_SELECTORS) {
    const attrTagPattern = new RegExp(`<[^>]*\\b${attr}\\b[^>]*>`, "i");
    if (!attrTagPattern.test(htmlContent)) {
      missingDataSelectors.push(attr);
    }
  }

  for (const sw of CONTRACT.SWITCHES) {
    const swPattern = new RegExp(`id=["']${sw.el}["']`, "i");
    if (!swPattern.test(htmlContent)) {
      missingSwitches.push(sw.el);
    }
  }

  // 提取并沙箱运行内联脚本
  const scriptMatch = htmlContent.match(/<script(?![^>]*src=)>([\s\S]*?)<\/script>/i);
  let scriptEvaluationError: string | null = null;
  const missingGlobals: string[] = [];
  const missingStateFields: string[] = [];

  if (!scriptMatch) {
    scriptEvaluationError = "未找到内联 <script> 标签";
  } else {
    const makeEl = () => new Proxy({}, {
      get: (target, prop) => {
        if (prop === "addEventListener") return () => {};
        if (prop === "querySelectorAll") return () => [];
        if (prop === "querySelector") return () => makeEl();
        if (prop === "dataset") return {};
        if (prop === "classList") return { add() {}, remove() {}, toggle() {} };
        if (prop === "setAttribute") return () => {};
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
      console: { log: () => {}, error: () => {} },
      setTimeout: () => {},
      setInterval: () => {},
      clearInterval: () => {},
      clearTimeout: () => {},
      localStorage: { getItem: () => null, setItem: () => {} },
      matchMedia: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }),
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;

    try {
      const context = vm.createContext(sandbox);
      vm.runInContext(scriptMatch[1], context);

      for (const fn of CONTRACT.GLOBAL_FUNCTIONS) {
        const type = vm.runInContext(`typeof ${fn}`, context);
        if (type !== "function") {
          missingGlobals.push(`${fn} (expected function, got ${type})`);
        }
      }

      for (const c of CONTRACT.GLOBAL_CONSTANTS) {
        const exists = vm.runInContext(`typeof ${c} !== "undefined"`, context);
        if (!exists) {
          missingGlobals.push(`${c} (expected constant, got undefined)`);
        }
      }

      for (const prop of CONTRACT.STATE_FIELDS) {
        const hasProp = vm.runInContext(`typeof state !== "undefined" && state && "${prop}" in state`, context);
        if (!hasProp) {
          missingStateFields.push(prop);
        }
      }
    } catch (err) {
      scriptEvaluationError = err instanceof Error ? err.message : String(err);
    }
  }

  return {
    isConformant:
      missingStaticIds.length === 0 &&
      missingDynamicSignatures.length === 0 &&
      missingDataSelectors.length === 0 &&
      missingSwitches.length === 0 &&
      missingGlobals.length === 0 &&
      missingStateFields.length === 0 &&
      scriptEvaluationError === null,
    missingStaticIds,
    missingDynamicSignatures,
    missingDataSelectors,
    missingSwitches,
    missingGlobals,
    missingStateFields,
    scriptEvaluationError,
  };
}

describe("UI-V2 看板架构契约测试", () => {
  const htmlPath = path.resolve(__dirname, "../index.html");
  const htmlContent = fs.readFileSync(htmlPath, "utf-8");

  it("HTML 必须包含 main.ts 依赖的所有静态 DOM ID", () => {
    for (const id of CONTRACT.STATIC_DOM_IDS) {
      const idPattern = new RegExp(`id=["']${id}["']`, "i");
      expect(idPattern.test(htmlContent), `缺少必需的 DOM ID: #${id}`).toBe(true);
    }
  });

  it("HTML 与模板必须包含 main.ts 依赖的所有动态元素签名与 data 属性", () => {
    for (const sig of CONTRACT.DYNAMIC_SIGNATURES) {
      expect(htmlContent.includes(sig), `模板中缺少动态元素特征: ${sig}`).toBe(true);
    }
  });

  it("HTML 必须包含 SWITCHES 表对应的所有开关 ID", () => {
    for (const sw of CONTRACT.SWITCHES) {
      const swPattern = new RegExp(`id=["']${sw.el}["']`, "i");
      expect(swPattern.test(htmlContent), `SWITCHES 缺少元素: #${sw.el}`).toBe(true);
    }
  });

  it("HTML 必须包含所有用于事件委托的 data-* 选择器", () => {
    for (const attr of CONTRACT.DATA_SELECTORS) {
      expect(htmlContent.includes(attr), `缺少 data 选择器: [${attr}]`).toBe(true);
    }
  });

  it("内联脚本必须暴露 main.ts 所需的全部全局函数与常量", () => {
    const audit = auditKanbanContract(htmlContent);
    expect(audit.scriptEvaluationError).toBeNull();
    expect(audit.missingGlobals).toEqual([]);
  });

  it("全局 state 对象必须包含 main.ts 所需的核心属性", () => {
    const audit = auditKanbanContract(htmlContent);
    expect(audit.missingStateFields).toEqual([]);
  });

  it("契约审计工具能够精准检测出缺失契约（如 btnStart 缺失）", () => {
    // 验证审计器在契约缺失时会严格报警
    const brokenHtml = htmlContent.replace('id="btnStart"', 'id="deprecatedBtnStart"');
    const result = auditKanbanContract(brokenHtml);
    expect(result.isConformant).toBe(false);
    expect(result.missingStaticIds).toContain("btnStart");
  });

  it("对比桌面新看板与正式线契约的就绪状态", () => {
    const deskHtmlPath = "C:/Users/10639/Desktop/影音游戏/GameScript-Local/ui-v2/index.html";
    if (fs.existsSync(deskHtmlPath)) {
      const deskHtml = fs.readFileSync(deskHtmlPath, "utf-8");
      const result = auditKanbanContract(deskHtml);
      // 记录桌面新看板当前的合规性
      console.log("[Contract Audit - Desktop Kanban]");
      console.log("Is Conformant:", result.isConformant);
      console.log("Missing Static IDs:", result.missingStaticIds);
      console.log("Missing Dynamic Signatures:", result.missingDynamicSignatures);
      console.log("Missing Data Selectors:", result.missingDataSelectors);
      console.log("Missing Globals:", result.missingGlobals);
      console.log("Missing State Fields:", result.missingStateFields);

      // 跟车配对码移除后，桌面新看板契约全绿
      expect(result.missingStaticIds).toEqual([]);
      expect(result.missingDataSelectors).toEqual([]);
      expect(result.missingGlobals).toEqual([]);
      expect(result.missingDynamicSignatures).toEqual([]);
    }
  });
});
