import { enqueueConfigPatch, flushConfigQueue, setSettingsRevision, resetStickyFailure, currentSettingsRevision } from "./config_queue";
import { normalizeAttributeValues, restoreAttributeIds } from "./strategy_codec";
// Task 5：qtBridge 真实接线（设计规格 §7）。OD12 的 DOM/CSS 与内联脚本保持原样；
// 本模块只做三件事：
//   1) bridge 探测：production → qtBridge(QWebChannel)，dev/浏览器 → 诚实 mock；
//      初始化失败渲染显式报错页，不静默降级假数据。
//   2) get_snapshot() → 初始化 OD12 `state`（模式/流派/卡组/技能/线路/主题/关卡/
//      声望/接管预案），随后一切渲染走既有 OD12 函数。
//   3) intent 出口与信号回推：配置改动 → update_config/update_shell；
//      btnStart → validate_preflight → start_run（运行中同按钮变 stop_run）；
//      btnMin/btnClose → window_control；run_status_changed → 徽标/进度；
//      log_appended → 运行日志；snapshot_changed → 快照重渲染。
import type { DashboardBridge, ModeDTO, PreflightDTO, RunStatusDTO, SettingsDTO, SnapshotDTO, StrategyDTO, WindowLayout } from "./bridge/types";

// —— index.html 内联脚本暴露的全局（经典脚本 globalThis 绑定）——
/* eslint-disable @typescript-eslint/no-explicit-any */
declare const state: any;
declare const BUILDS: { id: string; skills: string[] }[];
declare const FACTIONS: { id: string }[];
declare const STAGE_MAX: Record<number, number>;
declare function $(id: string): HTMLElement;
declare function toast(msg: string): void;
declare function setSwitch(el: Element, on: boolean): void;
declare function setScene(scene: string): void;
declare function setCycle(n: number): void;
declare function refreshSummary(): void;
declare function renderChapterStage(): void;
declare function renderBuilds(): void;
declare function renderBonds(): void;
declare function renderNegatives(): void;
declare function renderPrestige(): void;
declare function renderTeamRules(): void;
declare function renderNames(): void;
declare function currentSkills(): string[];
declare function applyOfficial(id: string): void;
declare function compactContentHeight(): number;
declare function speakHud(phaseId: string, phaseName?: string): { say: string; extra: string; chip: string };
/** OD12 场景 ↔ 目录 mode_id（config/mode_specs.json）；带车复用 normal_farm 建房链。 */
const SCENE_TO_MODE_ID: Record<string, string> = {
  farm: "normal_farm",
  lead: "normal_farm",
  follow: "follow_team",
  hitch: "lobby_hitch",
};
const MODE_ID_TO_SCENE: Record<string, string> = {
  normal_farm: "farm",
  follow_team: "follow",
  lobby_hitch: "hitch",
};

/** 抽屉开关：DOM 按钮 ↔ OD12 state 键 ↔ SettingsDTO 字段。 */
const SWITCHES = [
  { el: "swSecret", stateKey: "autoSecret", field: "auto_secret_realm" },
  { el: "swCloseML", stateKey: "closeMainline", field: "auto_close_main_line" },
  { el: "swAutoArch", stateKey: "autoArch", field: "auto_archaeology" },
  { el: "swNewRoom", stateKey: "newRoom", field: "new_room_every_times" },
  { el: "swDragon", stateKey: "dragonPrefer", field: "find_longzhu_where_multi_game" },
] as const;

/** 声望阵营 slug ↔ mediator FACTION_SPECS 数字键。 */
const FACTION_NUMBERS = { heifeng: 1, yinse: 2, kenrito: 3, tanxian: 4, yuansu: 5, shouhu: 6 } as const;
const FACTION_SLUGS: Record<string, string> = Object.fromEntries(
  Object.entries(FACTION_NUMBERS).map(([slug, num]) => [String(num), slug]),
);

const ACTIVE_RUN_STATES = new Set(["STARTING", "RUNNING", "STOPPING"]);
const RUN_STATE_LABELS: Record<string, string> = {
  IDLE: "待命",
  STARTING: "启动中",
  RUNNING: "运行中",
  STOPPING: "停止中",
  COMPLETE: "已完成",
  FAILED: "运行失败",
};
const LOG_TAIL_LINES = 60;

let bridge: DashboardBridge | null = null;
/** 应用远端快照期间为 true：抑制本地 intent 回写，防信号回环。 */
let applying = false;
let runActive = false;
let startBusy = false;
let modeCatalog = new Map<string, ModeDTO>();
let lastShellJson = "";
let lastWindowLayout = "";
let lastPreflight: { modeId: string; settingsRevision: number; result: PreflightDTO } | null = null;

export function getBridge(): DashboardBridge | null {
  return bridge;
}

// ---------------------------------------------------------------- 工具

function escText(s: string): string {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));
}

function asString(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function asStringList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

function clampCycle(n: number): number {
  return Math.max(0, Math.min(999, Math.trunc(n)));
}

export type HitchSearchTerms = { terms: string[]; primary: string; secondary: string };

export function parseHitchSearchTerms(value: unknown): HitchSearchTerms {
  const terms = String(value ?? "").replace(/，/g, ",").split(",")
    .map((term) => term.trim()).filter(Boolean);
  const unique = Array.from(new Set(terms));
  const list = unique.length > 0 ? unique : ["4", "3", "速"];
  return { terms: list, primary: list[0] ?? "4", secondary: list[1] ?? "3" };
}

let hitchSearchTerms: HitchSearchTerms = parseHitchSearchTerms("4,3,速");

function bridgeErrorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * 在既有全局函数后追加副作用钩子（函数声明是 globalThis 可写属性，
 * 内联脚本经全局作用域解析到替换后的实现）。快照应用期间钩子静默。
 */
function afterGlobalCall(name: string, hook: () => void): void {
  const g = globalThis as unknown as Record<string, unknown>;
  const orig = g[name];
  if (typeof orig !== "function") return;
  g[name] = (...args: unknown[]) => {
    (orig as (...a: unknown[]) => void)(...args);
    if (!applying) hook();
  };
}

// ---------------------------------------------------------------- intent 出口

function pushConfig(patch: Partial<SettingsDTO> & { strategy?: Partial<StrategyDTO> }): void {
  if (!bridge || applying) return;
  // Any settings mutation invalidates the previous backend preflight.  The
  // launch indicator must not keep advertising a result for stale settings.
  lastPreflight = null;
  applyLaunchability();
  enqueueConfigPatch(patch, bridge)
    .then((res) => {
      if (!res.ok) {
        toast("保存被拒绝: " + (res.errors[0] || "未知原因"));
      }
    })
    .catch((err) => toast(bridgeErrorText(err)));
}

function pushShell(patch: { theme?: "light" | "dark"; selected_mode_id?: string }): void {
  if (!bridge || applying) return;
  const json = JSON.stringify(patch);
  if (json === lastShellJson) return;
  lastShellJson = json;
  bridge.update_shell(patch)
    .then((res) => {
      if (!res.ok) toast(`保存被拒绝：${res.errors[0] ?? "未知原因"}`);
    })
    .catch((err) => toast(bridgeErrorText(err)));
}

function requestWindowLayout(layout: WindowLayout, height?: number): Promise<void> {
  const b = bridge;
  if (!b) return Promise.resolve();
  const key = height === undefined ? layout : `${layout}:${height}`;
  if (key === lastWindowLayout) return Promise.resolve();
  lastWindowLayout = key;
  return b.set_window_layout(layout, height).then(() => undefined, (err) => {
    if (lastWindowLayout === key) lastWindowLayout = "";
    console.error("[ui-v2] 窗口尺寸同步失败:", err);
  });
}

const nextFrame = () => new Promise<void>((r) => requestAnimationFrame(() => r()));

function measureCompact(): number {
  const h = typeof compactContentHeight === "function" ? compactContentHeight() : 640;
  return Math.max(1, Math.round(h));
}

function syncWindowLayout(scene: string): void {
  if (!bridge) return;
  if (scene === "hitch" || scene === "follow") {
    // 蹭车/跟车 = 二级小窗：360 宽，高度按内容实测。第一次是在大窗宽度下量的，
    // 窗口缩到 360 后内容会换行变高，所以缩完再量一次校正（最多两轮）。
    void (async () => {
      await nextFrame();
      for (let round = 0; round < 3; round += 1) {
        if (state.scene !== scene) return;
        const h = measureCompact();
        if (round > 0 && Math.abs(h - window.innerHeight) <= 2) return;
        await requestWindowLayout("compact", h);
        await nextFrame();
        await nextFrame();
      }
    })();
    return;
  }
  requestWindowLayout(scene === "wizard"
    ? (String(state.wizKind) === "team" ? "chooser-team" : "chooser-solo")
    : "dashboard");
}

function showStartErr(msg: string): void {
  const el = $("startErr");
  el.textContent = msg;
  el.classList.toggle("show", Boolean(msg));
}

let lastSkillsKey = "";
function pushSkills(): void {
  const skills = currentSkills().filter(Boolean);
  const priority = state.priority ? state.priority.slice() : [];
  const routes = state.routes ? { ...state.routes } : {};
  const key = JSON.stringify({ skills, priority, routes });
  if (key === lastSkillsKey) return;
  lastSkillsKey = key;
  pushConfig({
    strategy: {
      skills,
    },
    skill_priority: priority,
    skill_custom_routes: routes,
  });
}

function pushReputation(): void {
  const allocations: Record<string, number> = {};
  for (const faction of FACTIONS) {
    const points = Number(state.alloc[faction.id]) || 0;
    if (points > 0) allocations[String(FACTION_NUMBERS[faction.id as keyof typeof FACTION_NUMBERS])] = points;
  }
  pushConfig({ reputation_allocations: allocations, auto_reputation: Boolean(state.hero) });
}

const ADV_PACK_CARDS: Record<string, string[]> = {
  daodao: ["刀刀", "幽灵系带", "护腕", "空灵挂坠", "刀刀萌新", "刀刀大成"],
  yihuo: ["异火", "焚诀·黄阶", "阴阳双炎", "风怒龙炎", "幽冥毒火", "玄黄炎"],
  dasheng: ["齐天大圣", "大圣", "天命人", "大圣残躯", "大圣套装"],
  xiuxian: ["修仙", "筑基丹", "金丹大道", "元神出窍", "修仙萌新", "修仙大成"],
  fengshen: ["封神", "封神榜", "打神鞭", "杏黄旗", "斩仙飞刀", "肉身成圣"],
  haidao: ["海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏"],
  wangling: ["亡灵", "亡灵天灾", "白骨复生", "魂火收割", "巫妖之躯"],
};

function pushBondsAndAttributes(): void {
  const rawAttrs = Array.isArray(state.attr) ? state.attr : Array.from(state.attr || []);
  const activeAttrs = normalizeAttributeValues(rawAttrs);

  const validBonds = ["祝福", "成长", "经济", "贪婪", "挑战"];
  const growthList = Array.isArray(state.growth) ? state.growth : Array.from(state.growth || []);
  const bondsList = Array.isArray(state.bonds) ? state.bonds : Array.from(state.bonds || []);
  const combinedBonds = Array.from(new Set([...growthList, ...bondsList])).filter((b: string) => validBonds.includes(b)) as ("祝福" | "成长" | "经济" | "贪婪" | "挑战")[];
  // 空选择同样要落盘，不能偷偷回退成“全拿”。局内 hard 白名单只读此列表和 cards。
  const activeBonds = combinedBonds;

  const selectedAdv = Array.isArray(state.adv) ? state.adv : Array.from(state.adv || []);
  const selectedBasic = Array.isArray(state.basic) ? state.basic : Array.from(state.basic || []);
  const expandedCards: string[] = [];
  for (const packId of selectedAdv) {
    if (ADV_PACK_CARDS[packId]) {
      expandedCards.push(...ADV_PACK_CARDS[packId]);
    } else {
      expandedCards.push(packId);
    }
  }
  expandedCards.push(...selectedBasic);
  const activeCards = Array.from(new Set(expandedCards));

  pushConfig({
    cards: activeCards,
    bond_whitelist_mode: "hard",
    bond_must_take: [],
    strategy: {
      bonds: activeBonds,
      attributes: activeAttrs,
    },
  });
}

function pushNegatives(): void {
  const negatives = Array.isArray(state.negative) ? state.negative : Array.from(state.negative || []);
  pushConfig({
    treasure_allow_negative: negatives,
    strategy: {
      treasure: { negative_allowlist: negatives },
    },
  });
}



function currentModeId(): string {
  return SCENE_TO_MODE_ID[String(state.scene)] ?? "normal_farm";
}

/** OD12 只负责展示；是否能点火始终以后端 mode catalog 为准。 */
function applyLaunchability(): void {
  const evidence = $("evidencePill");
  const mode = modeCatalog.get(currentModeId());
  if (evidence) {
    const historical = mode?.evidence_status?.trim() || "unknown";
    const current = mode?.current_evidence?.status?.trim() || "MISSING";
    const reason = mode?.current_evidence?.reason?.trim() || "未提供原因";
    const buildCheck = lastPreflight?.modeId === currentModeId()
      ? lastPreflight.result.checks.find((check) => check.id === "build_identity")
      : null;
    const ocrCheck = lastPreflight?.modeId === currentModeId()
      ? lastPreflight.result.checks.find((check) => check.id === "ocr_runtime")
      : null;
    const identity = mode?.current_evidence;
    const identityDetail = [
      identity?.version ? `version=${identity.version}` : "",
      identity?.release_channel ? `release_channel=${identity.release_channel}` : "",
      identity?.source_sha ? `source_sha=${identity.source_sha}` : "",
      identity?.release_manifest_sha256 ? `manifest_sha256=${identity.release_manifest_sha256}` : "",
      identity?.exe_sha256 ? `exe_sha256=${identity.exe_sha256}` : "",
      identity?.bridge_schema_version ? `bridge_schema=${identity.bridge_schema_version}` : "",
      identity?.ocr_model_sha256 ? `ocr_model_sha256=${identity.ocr_model_sha256}` : "",
    ].filter(Boolean).join("；");
    evidence.textContent = `当前证据：${current}`;
    evidence.title = mode
      ? `${mode.label} 当前构建证据：${current}（${reason}）；历史覆盖：${historical}`
        + (identityDetail ? `；当前构建身份：${identityDetail}` : "")
        + (buildCheck ? `；构建身份：${buildCheck.detail}` : "")
        + (ocrCheck ? `；OCR：${ocrCheck.detail}` : "")
      : "当前运行方式证据状态未知";
    evidence.dataset.status = current;
    evidence.dataset.historicalStatus = historical;
    const identityPill = $("identityPill");
    if (identityPill) {
      const version = identity?.version || "";
      const channel = identity?.release_channel || "";
      const sourceShort = identity?.source_sha?.slice(0, 12) || "";
      const manifestShort = identity?.release_manifest_sha256?.slice(0, 12) || "";
      const modelShort = identity?.ocr_model_sha256?.slice(0, 12) || "";
      identityPill.textContent = sourceShort
        ? `v${version || "?"} · ${channel || "source"} · 构建 ${sourceShort} · 清单 ${manifestShort || "待补"} · 模型 ${modelShort || "待补"}`
        : "构建身份：待预检";
      identityPill.title = identityDetail || buildCheck?.detail || "后端预检后显示 version、release_channel、source_sha、整包 manifest、EXE、桥接和 OCR 模型哈希";
      identityPill.dataset.status = buildCheck?.ok === false ? "FAIL" : (identityDetail ? "READY" : "PENDING");
      const versionLabel = $("versionLabel");
      if (versionLabel) {
        const verStr = version ? (version.startsWith("v") ? version : `v${version}`) : "v0.3";
        versionLabel.textContent = `${verStr} · UI-23`;
        versionLabel.title = [
          version ? `version=${version}` : "",
          channel ? `release_channel=${channel}` : "",
          identity?.source_sha ? `source_sha=${identity.source_sha}` : (sourceShort ? `source_sha=${sourceShort}` : ""),
          identity?.release_manifest_sha256 ? `manifest_sha256=${identity.release_manifest_sha256}` : (manifestShort ? `manifest_sha=${manifestShort}` : ""),
          identity?.exe_sha256 ? `exe_sha256=${identity.exe_sha256}` : "",
          identity?.ocr_model_sha256 ? `ocr_model_sha256=${identity.ocr_model_sha256}` : (modelShort ? `ocr_model_sha=${modelShort}` : ""),
          "ui_build=UI-23",
        ].filter(Boolean).join(" · ") || "构建身份：待预检";
      }
    }
  }
  if (runActive) return;
  const skillsReady = currentSkills().filter(Boolean).length > 0;
  const locallyLaunchable = Boolean(mode?.startable) && skillsReady;
  const preflightCurrent = lastPreflight
    && lastPreflight.modeId === currentModeId()
    && lastPreflight.settingsRevision === Number(state.settings_revision ?? 0)
    ? lastPreflight.result
    : null;
  const button = $("btnStart") as HTMLButtonElement;
  // Local checks decide whether the user can request a backend preflight;
  // only the backend result may claim that the run is actually ready.
  button.disabled = !locallyLaunchable;
  const textRunEl = document.getElementById("btnStartTextRun");
  if (textRunEl) {
    textRunEl.textContent = locallyLaunchable ? "开始运行" : "不可启动";
  } else {
    button.textContent = locallyLaunchable ? "开始运行" : "不可启动";
  }
  button.classList.remove("stop");
  const backendReady = locallyLaunchable && Boolean(preflightCurrent?.ok);
  $("lamp").className = "lamp" + (backendReady ? "" : (locallyLaunchable ? " pending" : " bad"));
  $("lampText").textContent = backendReady
    ? "预检通过"
    : (mode?.startable ? (skillsReady ? "等待后端预检" : "待选技能") : "不可启动");
  if (!mode?.startable) {
    showStartErr(mode?.blocked_reason || "后端未开放此运行方式");
  } else if (!skillsReady) {
    showStartErr("请先选择至少一个技能");
  } else if (preflightCurrent && !preflightCurrent.ok) {
    showStartErr(preflightCurrent.blocked_reason || "预检未通过");
  } else {
    showStartErr("");
  }
}

async function startRun(): Promise<void> {
  const b = bridge;
  if (!b || startBusy) return;
  const modeId = currentModeId();
  startBusy = true;
  try {
    // 必须前置 await flushConfigQueue，确保所有 pending 配置已落盘并获得最新 revision
    await flushConfigQueue();

    // §6.3：UI 先本地预检给反馈；start_run 内部还会再验一次（fail-closed）。
    const pf = await b.validate_preflight(modeId);
    lastPreflight = {
      modeId,
      settingsRevision: Number(pf.settings_revision ?? state.settings_revision ?? 0),
      result: pf,
    };
    applyLaunchability();
    if (!pf.ok) {
      showStartErr(pf.blocked_reason || "预检未通过");
      return;
    }
    const res = await b.start_run(modeId, currentSettingsRevision);
    if (!res.ok) {
      showStartErr(res.error || "启动失败");
      toast(res.error || "启动失败");
    } else {
      toast("启动请求已受理");
    }
  } catch (err) {
    showStartErr(bridgeErrorText(err));
  } finally {
    startBusy = false;
  }
}

// ---------------------------------------------------------------- 快照 → state

function applyTheme(theme: unknown): void {
  if ((theme === "light" || theme === "dark") && theme !== state.theme) {
    state.theme = theme;
    $("scene-app").dataset.theme = theme;
    document.body.dataset.theme = theme;
    $("btnTheme").textContent = theme === "dark" ? "浅色" : "深色";
    $("btnTheme").setAttribute("aria-pressed", String(theme === "dark"));
    $("btnTheme").setAttribute("aria-label", theme === "dark" ? "当前深色，切换到浅色" : "当前浅色，切换到深色");
  }
}

function applyMode(shellModeId: unknown): void {
  const modeId = asString(shellModeId) ?? "";
  if (SCENE_TO_MODE_ID[String(state.scene)] === modeId) return;
  const scene = MODE_ID_TO_SCENE[modeId] ?? null;
  if (scene && scene !== state.scene) setScene(scene);
}

function applyCycle(v: unknown): void {
  if (typeof v === "number" && Number.isFinite(v)) setCycle(clampCycle(v));
}

function applyStageTargets(settings: SettingsDTO): void {
  const target = asStringList(settings.stage_targets)[0] ?? "";
  const m = /^(\d+)-(\d+)$/.exec(target);
  if (!m) return;
  const chapter = Number(m[1]);
  if (!(chapter >= 1 && chapter <= 4)) return;
  state.chapter = chapter;
  state.stage = Math.max(1, Math.min(Number(m[2]), STAGE_MAX[chapter] ?? Number(m[2])));
}

function applyDowngradeFailures(v: unknown): void {
  if (typeof v !== "number" || !Number.isFinite(v)) return;
  const input = document.getElementById("downgradeAfterFailures") as HTMLInputElement | null;
  if (input) input.value = String(Math.max(0, Math.min(20, Math.trunc(v))));
}

function applyBuildAndSkills(settings: SettingsDTO): void {
  const skills = asStringList(settings.skills).slice(0, 4);
  if (!skills.length) return; // 空技能保持壳内现状，交给 preflight 报错
  const official = BUILDS.find((b) => b.skills.length === skills.length && b.skills.every((c) => skills.includes(c)));
  if (official) {
    state.selected = official.id;
    // 快照中的卡组、属性和发育选择已在 applySnapshot 中回填。这里仅识别
    // 流派，不能再套用流派默认值，否则会清掉刚保存的高级卡组顺序。
  } else {
    const row = state.custom[0] ?? (state.custom[0] = { id: "custom:1", name: "自定义", skills: [] });
    row.skills = skills.slice();
    state.selected = row.id;
  }
  if (typeof state.collapsed !== "boolean") {
    state.collapsed = true;
  }
  const priority = asStringList(settings.skill_priority).filter((c) => currentSkills().includes(c));
  state.priority = [...priority, ...currentSkills().filter((c) => !priority.includes(c))].slice(0, 4);
  if (settings.skill_custom_routes && typeof settings.skill_custom_routes === "object") {
    Object.assign(state.routes, settings.skill_custom_routes);
  }
}

function applyPrestige(settings: SettingsDTO): void {
  const raw = settings.reputation_allocations;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const alloc: Record<string, number> = {};
    for (const [num, points] of Object.entries(raw as Record<string, unknown>)) {
      const slug = FACTION_SLUGS[num];
      const n = Number(points);
      if (slug && Number.isInteger(n) && n >= 0 && n <= 10) alloc[slug] = n;
    }
    if (Object.keys(alloc).length) state.alloc = { ...state.alloc, ...alloc };
  }
  if (typeof settings.auto_reputation === "boolean") state.hero = settings.auto_reputation;
}

function applyTeamRules(settings: SettingsDTO): void {
  const rules = state.teamRules;
  if (typeof settings.follow_cycle_num === "number") rules.follow.cycle = clampCycle(settings.follow_cycle_num);
  if (typeof settings.hitch_cycle_num === "number") rules.hitch.cycle = clampCycle(settings.hitch_cycle_num);
  const afterRoom = asString(settings.follow_after_room);
  if (afterRoom) rules.follow.afterRoom = afterRoom;
  const afterGoal = asString(settings.hitch_after_goal);
  if (afterGoal) rules.hitch.afterGoal = afterGoal;
  const pairCode = asString(settings.follow_pair_code);
  if (pairCode !== null) rules.follow.pairCode = pairCode;
}

function applySwitches(settings: SettingsDTO): void {
  for (const sw of SWITCHES) {
    const value = (settings as Record<string, unknown>)[sw.field];
    if (typeof value === "boolean") {
      state[sw.stateKey] = value;
      setSwitch($(sw.el), value);
    }
  }
}

function renderHitchSearchSummary(): void {
  const el = document.getElementById("hitchSearchSummary");
  if (el) el.textContent = hitchSearchTerms.terms.join(", ") || "未设置";
}

let modalDraftTerms: string[] = [];

function renderHitchModalContent(): void {
  const container = document.getElementById("hitchTermsContainer");
  if (!container) return;
  container.innerHTML = modalDraftTerms.map((term, i) => `
    <div class="hitch-term-row" style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
      <span style="font-size:12px;color:var(--p-faint);width:16px;text-align:right;">${i + 1}</span>
      <input type="text" class="hitch-term-input" data-idx="${i}" maxlength="32" value="${escText(term)}" placeholder="如 4、3、速" style="flex:1;min-width:0;height:32px;padding:0 8px;border:1px solid var(--p-line);border-radius:6px;background:var(--p-bg);color:var(--p-ink);font-size:13px;" autocomplete="off" />
      <button type="button" class="term-nav-btn" data-term-move="-1" data-idx="${i}" ${i === 0 ? "disabled" : ""} title="上移" style="width:28px;height:28px;padding:0;border:1px solid var(--p-line);border-radius:6px;background:var(--p-paper);color:var(--p-ink);cursor:pointer;">▲</button>
      <button type="button" class="term-nav-btn" data-term-move="1" data-idx="${i}" ${i === modalDraftTerms.length - 1 ? "disabled" : ""} title="下移" style="width:28px;height:28px;padding:0;border:1px solid var(--p-line);border-radius:6px;background:var(--p-paper);color:var(--p-ink);cursor:pointer;">▼</button>
      <button type="button" class="term-nav-btn" data-term-del="${i}" title="删除" style="width:28px;height:28px;padding:0;border:1px solid var(--p-line);border-radius:6px;background:var(--p-paper);color:var(--p-danger, #e55);cursor:pointer;">✕</button>
    </div>
  `).join("");
  updateHitchCharCount();
}

function syncModalDraftFromInputs(): void {
  const inputs = document.querySelectorAll<HTMLInputElement>(".hitch-term-input");
  inputs.forEach((input) => {
    const idx = Number(input.dataset.idx);
    if (idx >= 0 && idx < modalDraftTerms.length) {
      modalDraftTerms[idx] = input.value;
    }
  });
}

function updateHitchCharCount(): void {
  const countEl = document.getElementById("hitchTermsCharCount");
  if (!countEl) return;
  const filtered = modalDraftTerms.map((t) => t.trim()).filter(Boolean);
  const unique = Array.from(new Set(filtered));
  const totalLen = unique.join(",").length;
  countEl.textContent = `合计 ${totalLen}/64 字符`;
  countEl.style.color = totalLen > 64 ? "var(--p-danger, #e55)" : "var(--p-faint)";
}

function rerenderAll(settings: SettingsDTO): void {
  renderChapterStage();
  hitchSearchTerms = parseHitchSearchTerms(settings.hitch_stage_prefix);
  (window as unknown as { hitchSearchTerms: HitchSearchTerms }).hitchSearchTerms = hitchSearchTerms;
  renderHitchSearchSummary();
  const cjb = asString(settings.cjb_boss); // 持久化选择压过推荐展示
  const boss = asString(settings.sgzx_boss);
  if (cjb) state.cjb = cjb;
  if (boss) state.boss = boss;
  renderNames();
  renderBuilds();
  renderBonds();
  renderPrestige();
  renderTeamRules();
  renderNegatives();
  refreshSummary(); // 内含 renderLaunchSummary
}

function openHitchSearchModal(): void {
  state.modal = "hitch_search";
  state._focusBack = document.activeElement;
  modalDraftTerms = hitchSearchTerms.terms.length ? [...hitchSearchTerms.terms] : ["4", "3", "速"];
  const sheet = $("modalSheet");
  sheet.className = "sheet";
  sheet.innerHTML = `<div class="sheet-head"><h2 id="sheetTitle">高级搜房</h2></div>` +
    `<div class="sheet-body"><p class="hint" style="margin:0 0 10px;font-size:12px;color:var(--p-muted);line-height:1.4;">大厅找房时按顺序依次轮换。支持中文或任意文字（例如「速」「刷」「秘境」），合计上限 64 字符。</p>` +
    `<div id="hitchTermsContainer" style="max-height:240px;overflow-y:auto;padding-right:4px;"></div>` +
    `<div style="margin-top:8px;display:flex;align-items:center;justify-content:space-between;">` +
    `<button type="button" class="text-btn" id="btnAddHitchTerm" style="font-size:12px;cursor:pointer;">+ 添加搜房词</button>` +
    `<span id="hitchTermsCharCount" style="font-size:11px;color:var(--p-faint);"></span>` +
    `</div></div>` +
    `<div class="sheet-nav"><button type="button" class="secondary" data-close="1">取消</button><span class="grow"></span><button type="button" class="gold" data-apply-hitch-search="1">保存</button></div>`;
  renderHitchModalContent();
  $("modalLayer").classList.add("show");
  (sheet.querySelector(".hitch-term-input") as HTMLInputElement | null)?.focus();
}

function applyVisibleSettings(): void {
  const modeId = currentModeId();
  const mode = modeCatalog.get(modeId);
  if (!mode || !Array.isArray(mode.visible_settings)) return;
  const vis = new Set(mode.visible_settings);
  const hitchCjb = document.getElementById("hitchCjbCard");
  const hitchBoss = document.getElementById("hitchBossCard");
  const followCjb = document.getElementById("followCjbCard");
  const followBoss = document.getElementById("followBossCard");
  const btnHitchAdv = document.getElementById("btnHitchAdvanced");
  const hitchSearch = document.getElementById("hitchSearchCard");
  if (hitchCjb) hitchCjb.style.display = vis.has("cjb_boss") ? "" : "none";
  if (hitchBoss) hitchBoss.style.display = vis.has("sgzx_boss") ? "" : "none";
  if (followCjb) followCjb.style.display = vis.has("cjb_boss") ? "" : "none";
  if (followBoss) followBoss.style.display = vis.has("sgzx_boss") ? "" : "none";
  if (btnHitchAdv) btnHitchAdv.style.display = vis.has("hitch_stage_prefix") ? "" : "none";
  if (hitchSearch) hitchSearch.style.display = vis.has("hitch_stage_prefix") ? "" : "none";
}

let lastAppliedSnapshotSeq = 0;

export function applySnapshot(snap: SnapshotDTO): void {
  // 必须先检查 snapshot_seq stale gate，抛弃过时快照，再更新 settings_revision
  if (snap.snapshot_seq && snap.snapshot_seq <= lastAppliedSnapshotSeq) return;
  if (snap.snapshot_seq) lastAppliedSnapshotSeq = snap.snapshot_seq;
  if (snap.settings_revision !== undefined) {
    if (Number(snap.settings_revision) !== Number(state.settings_revision ?? 0)) {
      lastPreflight = null;
    }
    state.settings_revision = snap.settings_revision;
    setSettingsRevision(snap.settings_revision);
    resetStickyFailure();
  }
  applying = true;
  try {
    const settings: SettingsDTO = snap.settings ?? {};
    if (Array.isArray(snap.modes)) {
      modeCatalog = new Map(snap.modes.map((mode) => [mode.id, mode]));
    }
    if (snap.strategy) {
      if (Array.isArray(snap.strategy.skills)) settings.skills = snap.strategy.skills;
      if (Array.isArray(snap.strategy.bonds)) {
        settings.bonds = snap.strategy.bonds;
      }
      const savedCards = Array.isArray(snap.strategy.cards)
        ? snap.strategy.cards
        : Array.isArray(settings.cards)
        ? settings.cards
        : [];
      settings.cards = savedCards;
      // cards 的首个命中顺序就是高级卡组优先级；空数组同样要清空旧界面状态。
      const cardToPack = new Map<string, string>();
      for (const [packId, cardNames] of Object.entries(ADV_PACK_CARDS)) {
        for (const c of cardNames) cardToPack.set(c, packId);
      }
      const restoredAdv: string[] = [];
      for (const card of savedCards) {
        const packId = cardToPack.get(card) ?? (ADV_PACK_CARDS[card] ? card : "");
        if (packId && !restoredAdv.includes(packId)) restoredAdv.push(packId);
      }
      const basicNames = ["法术", "急速", "魔能", "魔术", "魔法师", "元素师", "箭术", "战术", "暴击", "固守", "陷阵"];
      state.adv = restoredAdv;
      state.advDraft = restoredAdv.slice();
      state.basic = new Set(basicNames.filter((name) => savedCards.includes(name)));
      if (Array.isArray(snap.strategy.bonds)) {
        state.growth = new Set(snap.strategy.bonds);
      }
      state.bondSaved = true;
      if (Array.isArray(snap.strategy.attributes)) {
        settings.attributes = snap.strategy.attributes;
        state.attr = restoreAttributeIds(snap.strategy.attributes);
      }
      if (snap.strategy.merchant) {
        settings.merchant_enabled = snap.strategy.merchant.enabled;
      }
      const negAllow = snap.strategy?.treasure?.negative_allowlist ?? (snap.settings?.treasure_allow_negative as string[] | undefined);
      if (Array.isArray(negAllow)) {
        settings.treasure_allow_negative = negAllow;
        state.negative = new Set(negAllow);
        const win = window as unknown as Record<string, unknown>;
        if (typeof win.renderNegatives === "function") {
          (win.renderNegatives as () => void)();
        }
      }
    }
    applyTheme(snap.shell?.theme);
    applyMode(snap.shell?.selected_mode_id);
    applyCycle(settings.cycle_num);
    applyTeamRules(settings);
    applySwitches(settings);
    applyPrestige(settings);
    applyStageTargets(settings);
    applyDowngradeFailures(settings.downgrade_after_failures);
    applyBuildAndSkills(settings);
    applyVisibleSettings();
    const roomName = asString(settings.room_name);
    const roomPassword = asString(settings.room_password);
    if (roomName !== null) ($("roomName") as HTMLInputElement).value = roomName;
    if (roomPassword !== null) ($("roomPass") as HTMLInputElement).value = roomPassword;
    applySubscription(snap.subscription);
    rerenderAll(settings);
    // The first snapshot is authoritative for a run that may already be
    // STARTING/COMPLETE/FAILED.  Do not wait for a later Qt signal or the
    // dashboard can briefly (or permanently, after a fast bootstrap failure)
    // show the wrong lifecycle state.
    if (snap.run) applyRunStatus(snap.run);
    applyLaunchability();
  } finally {
    applying = false;
  }
}

function applySubscription(sub?: { active?: boolean; status?: string; expires_at?: string; live_authorized?: boolean; live_status?: string }): void {
  const globalFn = (window as unknown as Record<string, unknown>).applySubscription;
  if (typeof globalFn === "function") {
    (globalFn as (s?: unknown) => void)(sub);
    return;
  }
  const pill = $("subscriptionPill");
  if (!pill) return;
  const isOk = Boolean(sub?.active);
  const status = sub?.status || "未激活";
  const exp = sub?.expires_at ? (sub.expires_at.length >= 10 ? sub.expires_at.substring(0, 10) : sub.expires_at) : "";
  pill.textContent = `${isOk ? `卡密有效${exp ? ` (${exp} 到期)` : ""}` : `订阅：${status}`} · ${sub?.live_status || "LIVE 授权待校验"}`;
  pill.dataset.state = sub?.live_authorized ? "ok" : "warn";
}

// ---------------------------------------------------------------- 运行态信号

function applyRunStatus(run: RunStatusDTO): void {
  runActive = ACTIVE_RUN_STATES.has(run.state);
  const label = RUN_STATE_LABELS[run.state] ?? run.state;
  // 阶段只显示中文短词（speakHud），不把 MAIN_LINE 这类枚举直接给用户看。
  const phaseChip = run.phase && runActive && typeof speakHud === "function" ? speakHud(run.phase).chip : "";
  $("statusPill").innerHTML = `<span class="dot"></span>${escText(label)}${phaseChip ? " · " + escText(phaseChip) : ""}`;
  const loadBar = $("loadBar");
  loadBar.classList.toggle("show", runActive);
  loadBar.setAttribute("aria-hidden", runActive ? "false" : "true");
  $("gamesToday").textContent = String(Math.max(0, Number(run.game_count) || 0));
  $("gamesCap").textContent = run.cycle_num > 0 ? String(run.cycle_num) : "手动";
  const btnStart = $("btnStart") as HTMLButtonElement;
  const textStopEl = document.getElementById("btnStartTextStop");
  const stopText = run.state === "STOPPING" ? "停止中…" : "停止运行";
  if (textStopEl) {
    textStopEl.textContent = stopText;
  }
  if (runActive) {
    if (!textStopEl) btnStart.textContent = stopText;
    btnStart.classList.add("stop");
    btnStart.disabled = run.state === "STOPPING";
  } else {
    btnStart.classList.remove("stop");
    refreshSummary(); // 恢复“开始运行”文案与可用性判定
    applyLaunchability();
  }
  const ctrlRunning = document.getElementById("ctrl-running") as HTMLInputElement | null;
  if (ctrlRunning) ctrlRunning.checked = runActive;
  document.body.dataset.running = runActive ? "true" : "false";
  state.running = runActive;
  state.runState = run.state;
  state.runModeId = run.mode_id;
  state.runSummary = run.summary ?? null;
  state.hudPhase = run.phase;
  state.played = Math.max(0, Number(run.game_count) || 0);
  if (run.cycle_num !== undefined) state.cycle = run.cycle_num;
  const win = window as unknown as Record<string, unknown>;
  if (typeof win.renderHud === "function") {
    (win.renderHud as () => void)();
  }
  if (run.state === "FAILED") {
    const msg = `${label}${run.terminal_reason ? "：" + run.terminal_reason : ""}`;
    showStartErr(msg);
    toast(msg);
  } else {
    showStartErr("");
  }
}

let runLogEl: HTMLElement | null = null;
let runLogAlerts = 0;

/** 日志收在「宝物设置」抽屉底部的折叠区（index.html #odRunLog），默认只显示 warn/error。 */
function ensureRunLogPanel(): HTMLElement {
  if (runLogEl) return runLogEl;
  const existing = document.getElementById("odRunLog");
  if (existing) {
    runLogEl = existing;
    const all = document.getElementById("runLogAll") as HTMLInputElement | null;
    all?.addEventListener("change", () => existing.classList.toggle("show-all", all.checked));
    return runLogEl;
  }
  // 旧 DOM 没有折叠区时的兜底：隐藏容器，只留 console 输出，绝不浮在界面上。
  runLogEl = document.createElement("div");
  runLogEl.id = "odRunLog";
  runLogEl.hidden = true;
  document.body.appendChild(runLogEl);
  return runLogEl;
}

function appendRunLog(text: string, level: string): void {
  console.log(`[run][${level}] ${text}`);
  const panel = ensureRunLogPanel();
  const lvl = String(level || "info").toLowerCase();
  const line = document.createElement("div");
  line.dataset.level = lvl;
  line.textContent = `[${lvl}] ${text}`;
  panel.appendChild(line);
  while (panel.childElementCount > LOG_TAIL_LINES) panel.removeChild(panel.firstChild as ChildNode);
  if (lvl === "warn" || lvl === "warning" || lvl === "error" || lvl === "critical") {
    runLogAlerts += 1;
    const sum = document.getElementById("runLogSum");
    if (sum) sum.textContent = `${runLogAlerts} 条告警`;
  }
  panel.scrollTop = panel.scrollHeight;
}

type FacadeSignals = {
  snapshot_changed: { connect(cb: (json: string) => void): void };
  run_status_changed: { connect(cb: (json: string) => void): void };
  log_appended: { connect(cb: (text: string, level: string) => void): void };
};

function wireSignals(signals: FacadeSignals): void {
  signals.run_status_changed.connect((json) => {
    try {
      applyRunStatus(JSON.parse(json) as RunStatusDTO);
    } catch (err) {
      console.error("[ui-v2] run_status_changed 载荷异常:", err);
    }
  });
  signals.log_appended.connect((text, level) => appendRunLog(String(text), String(level)));
  signals.snapshot_changed.connect((json) => {
    try {
      applySnapshot(JSON.parse(json) as SnapshotDTO);
    } catch (err) {
      console.error("[ui-v2] snapshot_changed 载荷异常:", err);
    }
  });
}

// ---------------------------------------------------------------- intent 接线

function defer(fn: () => void): void {
  setTimeout(fn, 0); // 让同一事件上先注册的 OD12 处理器改完 state 再读
}

function wireIntents(): void {
  // 全局函数后钩子：每个全局操作挂一次钩子
  afterGlobalCall("setCycle", () => pushConfig({ cycle_num: clampCycle(Number(state.cycle)) }));
  afterGlobalCall("renderChapterStage", () => pushConfig({ stage_targets: [`${state.chapter}-${state.stage}`] }));
  const downgrade = document.getElementById("downgradeAfterFailures") as HTMLInputElement | null;
  downgrade?.addEventListener("change", () => {
    const value = Math.max(0, Math.min(20, Math.trunc(Number(downgrade.value) || 0)));
    downgrade.value = String(value);
    pushConfig({ downgrade_after_failures: value });
  });
  afterGlobalCall("renderSkillRank", () => {
    if (state.collapsed) pushSkills();
  });
  afterGlobalCall("selectBuild", () => {
    pushSkills();
    pushBondsAndAttributes();
  });
  afterGlobalCall("restorePresets", () => {
    pushSkills();
    pushBondsAndAttributes();
  });
  // 羁绊配置按用户显式点击“保存羁绊”落盘，避免每次重绘都产生一次配置请求。
  afterGlobalCall("renderNegatives", pushNegatives);
  afterGlobalCall("renderWizard", () => {
    if (String(state.scene) === "wizard") syncWindowLayout("wizard");
  });
  afterGlobalCall("refreshSummary", applyLaunchability);
  afterGlobalCall("setScene", () => {
    syncWindowLayout(String(state.scene));
    const modeId = SCENE_TO_MODE_ID[state.scene];
    if (modeId) {
      lastPreflight = null;
      pushShell({ selected_mode_id: modeId });
    }
    applyVisibleSettings();
  });

  // 常规开关与英雄挑战开关落盘接线
  for (const sw of SWITCHES) {
    const el = document.getElementById(sw.el);
    if (el) {
      el.addEventListener("click", () => {
        defer(() => pushConfig({ [sw.field]: Boolean(state[sw.stateKey]) }));
      });
    }
  }
  const heroEl = document.getElementById("swHero");
  if (heroEl) {
    heroEl.addEventListener("click", () => defer(pushReputation));
  }

  // 负面效果勾选变化事件
  const negEl = $("negatives");
  if (negEl) {
    negEl.addEventListener("change", () => defer(pushNegatives));
  }

  $("bonds").addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest("#btnSaveBonds")) {
      defer(() => pushBondsAndAttributes());
    }
  });

  // 摘要视图下调整高级卡组顺序：内联处理器已改 state.adv，这里补落盘，
  // 让“保存后仍可调序”无需再点一次保存。
  $("bonds").addEventListener("click", (e) => {
    if ((e.target as HTMLElement).closest("[data-adv-move], [data-adv-pick]") && state.bondSaved) {
      defer(() => pushBondsAndAttributes());
    }
  });

  // 技能路线下拉
  $("skillRank").addEventListener("change", (e) => {
    if ((e.target as HTMLElement).closest("[data-route]")) {
      pushConfig({ skill_custom_routes: { ...state.routes } });
    }
  });


  // 主题：index.html 在 View Transition 回调里（异步）才调 applyTheme，
  // 所以挂在 applyTheme 之后推送，不能在 click 时读 state.theme（会读到旧值并把主题改回去）。
  afterGlobalCall("applyTheme", () => pushShell({ theme: state.theme === "dark" ? "dark" : "light" }));

  // 配对码与接管预案（若有表单则兼容保留，跟车业务无配对码则安全跳过）。
  const followPairForm = document.getElementById("followPairForm");
  if (followPairForm) {
    followPairForm.addEventListener("submit", (e) => {
      e.preventDefault();
      defer(() => pushConfig({ follow_pair_code: String(state.teamRules.follow.pairCode ?? "") }));
    });
  }
  for (const [id, field] of [["roomName", "room_name"], ["roomPass", "room_password"]] as const) {
    $(id).addEventListener("change", (e) =>
      pushConfig({ [field]: (e.target as HTMLInputElement).value.trim() }),
    );
  }
  document.querySelectorAll("[data-team-rules]").forEach((root) => {
    const mode = (root as HTMLElement).dataset.teamRules;
    const push = () => {
      if (mode === "follow") {
        pushConfig({
          follow_cycle_num: clampCycle(Number(state.teamRules.follow.cycle)),
          follow_after_room: String(state.teamRules.follow.afterRoom ?? ""),
        });
      } else if (mode === "hitch") {
        pushConfig({
          hitch_cycle_num: clampCycle(Number(state.teamRules.hitch.cycle)),
          hitch_after_goal: String(state.teamRules.hitch.afterGoal ?? ""),
        });
      }
    };
    root.addEventListener("click", () => defer(push));
    root.addEventListener("change", () => defer(push));
  });
  // 模态层：传家宝/Boss 选定与声望分配落盘（capture 先于 OD12 冒泡处理器读取 kind）。
  $("modalLayer").addEventListener(
    "click",
    (e) => {
      const target = e.target as HTMLElement;
      const stemBtn = target.closest("[data-stem]");
      const applyRep = target.closest("[data-apply-rep]");
      if (!stemBtn && !applyRep) return;
      const kind = String(state.modal ?? "");
      defer(() => {
        if (applyRep) {
          pushReputation();
        } else if (kind === "boss") {
          pushConfig({ sgzx_boss: String(state.boss) });
        } else {
          pushConfig({ cjb_boss: String(state.cjb) });
        }
      });
    },
    { capture: true },
  );
  $("modalLayer").addEventListener("input", (event) => {
    if ((event.target as HTMLElement).matches(".hitch-term-input")) {
      syncModalDraftFromInputs();
      updateHitchCharCount();
    }
  });
  $("modalLayer").addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const addBtn = target.closest("#btnAddHitchTerm");
    if (addBtn) {
      syncModalDraftFromInputs();
      modalDraftTerms.push("");
      renderHitchModalContent();
      const inputs = document.querySelectorAll<HTMLInputElement>(".hitch-term-input");
      inputs[inputs.length - 1]?.focus();
      return;
    }
    const moveBtn = target.closest("[data-term-move]") as HTMLElement | null;
    if (moveBtn) {
      syncModalDraftFromInputs();
      const idx = Number(moveBtn.dataset.idx);
      const dir = Number(moveBtn.dataset.termMove);
      const targetIdx = idx + dir;
      if (targetIdx >= 0 && targetIdx < modalDraftTerms.length) {
        const tmp = modalDraftTerms[idx];
        modalDraftTerms[idx] = modalDraftTerms[targetIdx];
        modalDraftTerms[targetIdx] = tmp;
        renderHitchModalContent();
      }
      return;
    }
    const delBtn = target.closest("[data-term-del]") as HTMLElement | null;
    if (delBtn) {
      syncModalDraftFromInputs();
      const idx = Number(delBtn.dataset.termDel);
      modalDraftTerms.splice(idx, 1);
      if (!modalDraftTerms.length) modalDraftTerms.push("");
      renderHitchModalContent();
      return;
    }
    if (target.closest("[data-apply-hitch-search]")) {
      syncModalDraftFromInputs();
      const cleaned = modalDraftTerms.map((t) => t.trim()).filter(Boolean);
      const unique = Array.from(new Set(cleaned));
      const search = unique.join(",");
      if (!unique.length) {
        event.stopPropagation();
        toast("搜房词不能为空");
        return;
      }
      if (search.length > 64) {
        event.stopPropagation();
        toast("所有搜房词合计最多 64 个字符");
        return;
      }
      hitchSearchTerms = {
        terms: unique,
        primary: unique[0] ?? "4",
        secondary: unique[1] ?? "3",
      };
      (window as unknown as { hitchSearchTerms: HitchSearchTerms }).hitchSearchTerms = hitchSearchTerms;
      renderHitchSearchSummary();
      pushConfig({ hitch_stage_prefix: search });
      ((document.querySelector("#modalSheet [data-close]") as HTMLButtonElement | null))?.click();
      return;
    }
  }, { capture: true });
  $("btnHitchAdvanced").addEventListener("click", openHitchSearchModal);
  $("hitchSearchCard")?.addEventListener("click", openHitchSearchModal);

  // 启动 / 停止（同一按钮，运行态切换为 stop_run）。
  $("btnStart").addEventListener("click", () => {
    if (!bridge || startBusy) return;
    if (runActive) {
      bridge.stop_run()
        .then((res) => toast(res.ok ? "已请求停止" : `停止失败：${res.error ?? ""}`))
        .catch((err) => toast(bridgeErrorText(err)));
      return;
    }
    void startRun();
  });

  // 窗口控制。
  $("btnMin").addEventListener("click", () => void bridge?.window_control("minimize").catch(console.error));
  $("btnClose").addEventListener("click", () => void bridge?.window_control("close").catch(console.error));
  // 激活订阅卡密：使用看板内嵌引导层，不调用浏览器脚本框。
  $("btnActivateKey")?.addEventListener("click", async () => {
    const opener = (window as unknown as Record<string, unknown>).openSubscriptionModal;
    if (typeof opener === "function") (opener as () => void)();
  });
  $("modalLayer").addEventListener("click", async (event) => {
    const submit = (event.target as HTMLElement).closest("[data-activate-subscription]") as HTMLButtonElement | null;
    if (!submit) return;
    const key = (document.getElementById("subscriptionKey") as HTMLInputElement | null)?.value.trim() ?? "";
    if (!key) {
      toast("请输入卡密");
      return;
    }
    submit.disabled = true;
    try {
      const res = await (bridge
        ? bridge.activate_subscription(key)
        : Promise.resolve({ ok: false, message: "后端桥接未就绪", status: "", expires_at: "", subscription: undefined }));
      if (res && res.ok) {
        toast(res.message || "订阅激活成功！");
        applySubscription(res.subscription || { active: true, status: "卡密有效", expires_at: res.expires_at || "", live_authorized: false, live_status: "LIVE 授权待校验" });
        ((document.querySelector("#modalSheet [data-close]") as HTMLButtonElement | null))?.click();
      } else {
        toast("激活失败：" + (res?.message || "卡密无效"));
        if (res?.status) {
          applySubscription({ active: false, status: res.status, expires_at: res.expires_at || "" });
        }
      }
    } catch (err) {
      toast("激活请求异常：" + String(err));
    } finally {
      submit.disabled = false;
    }
  });
}

// ---------------------------------------------------------------- 启动

function showFatal(err: unknown): void {
  console.error("[ui-v2] bridge 初始化失败:", err);
  const app = $("scene-app");
  if (!app) return;
  app.innerHTML = `<div style="padding:40px"><h2 style="margin:0 0 12px">桥接初始化失败</h2>` +
    `<p style="white-space:pre-wrap">${escText(bridgeErrorText(err))}</p>` +
    `<p>请重启应用重试；页面不会降级为假数据。</p></div>`;
}

async function boot(): Promise<void> {
  if (import.meta.env.MODE !== "production") {
    // dev/浏览器测试：诚实 mock，形状与 types.ts 一致；生产构建不打包此分支。
    const { createMockBridgeConnection } = await import("./bridge/mockBridge");
    const conn = createMockBridgeConnection();
    bridge = conn.bridge;
    wireSignals(conn.signals);
  } else {
    const { createQtBridge } = await import("./bridge/qtBridge");
    const conn = await createQtBridge();
    bridge = conn.bridge;
    wireSignals(conn.signals);
  }
  wireIntents();
  applySnapshot(await bridge.get_snapshot());
}

if (typeof window !== "undefined" && typeof document !== "undefined" && document.getElementById("scene-app")) {
  boot().catch(showFatal);
}
