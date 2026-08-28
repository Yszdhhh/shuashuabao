import { enqueueConfigPatch, flushConfigQueue, setSettingsRevision, resetStickyFailure, currentSettingsRevision } from "./config_queue";
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
import type { DashboardBridge, ModeDTO, RunStatusDTO, SettingsDTO, SnapshotDTO, StrategyDTO } from "./bridge/types";

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
declare function recommendChallenges(): void;
declare function currentSkills(): string[];
declare function applyOfficial(id: string): void;
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
const LOG_TAIL_LINES = 8;

let bridge: DashboardBridge | null = null;
/** 应用远端快照期间为 true：抑制本地 intent 回写，防信号回环。 */
let applying = false;
let runActive = false;
let startBusy = false;
let modeCatalog = new Map<string, ModeDTO>();
let lastShellJson = "";

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

function syncWindowLayout(scene: string): void {
  if (!bridge) return;
  const layout = scene === "wizard" ? "chooser" : "dashboard";
  bridge.set_window_layout(layout).catch((err) => console.error("[ui-v2] 窗口尺寸同步失败:", err));
}

function showStartErr(msg: string): void {
  const el = $("startErr");
  el.textContent = msg;
  el.classList.toggle("show", Boolean(msg));
}

function pushSkills(): void {
  pushConfig({
    strategy: {
      skills: currentSkills().filter(Boolean),
    },
    skill_priority: state.priority.slice(),
  });
}

function pushReputation(): void {
  const allocations: Record<string, number> = {};
  let maxPoints = 0;
  for (const faction of FACTIONS) {
    const points = Number(state.alloc[faction.id]) || 0;
    if (points > 0) allocations[String(FACTION_NUMBERS[faction.id as keyof typeof FACTION_NUMBERS])] = points;
    maxPoints = Math.max(maxPoints, points);
  }
  pushConfig({ reputation_allocations: allocations, auto_reputation: Boolean(state.hero) || maxPoints > 0 });
}

const ADV_PACK_CARDS: Record<string, string[]> = {
  daodao: ["刀刀", "幽灵系带", "护腕", "空灵挂坠", "刀刀萌新", "刀刀大成"],
  yihuo: ["异火", "焚诀·黄阶", "阴阳双炎", "风怒龙炎", "幽冥毒火", "玄黄炎"],
  dasheng: ["齐天大圣", "大圣", "天命人", "大圣残躯", "大圣套装"],
  xiuxian: ["修仙", "筑基丹", "金丹大道", "元神出窍", "修仙萌新", "修仙大成"],
  fengshen: ["封神", "封神榜", "打神鞭", "杏黄旗", "斩仙飞刀"],
  haidao: ["海盗", "白赚海盗", "海盗劫掠者", "海盗宝藏"],
  wangling: ["亡灵", "亡灵天灾", "白骨复生", "魂火收割", "巫妖之躯"],
};

function pushBondsAndAttributes(): void {
  const rawAttrs = Array.isArray(state.attr) ? state.attr : Array.from(state.attr || []);
  const attrMap: Record<string, "int" | "str" | "agi"> = {
    intelligence: "int",
    strength: "str",
    agility: "agi",
    int: "int",
    str: "str",
    agi: "agi",
  };
  const activeAttrs = rawAttrs.map((a: string) => attrMap[a]).filter(Boolean) as ("int" | "str" | "agi")[];

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
  if (runActive) return;
  const mode = modeCatalog.get(currentModeId());
  const skillsReady = currentSkills().filter(Boolean).length > 0;
  const launchable = Boolean(mode?.startable) && skillsReady;
  const button = $("btnStart") as HTMLButtonElement;
  button.disabled = !launchable;
  button.textContent = launchable ? "开始运行" : "不可启动";
  button.classList.remove("stop");
  $("lamp").className = "lamp" + (launchable ? "" : " bad");
  $("lampText").textContent = launchable ? "预检通过" : (mode?.startable ? "待选技能" : "不可启动");
  showStartErr(launchable ? "" : (mode?.blocked_reason || (skillsReady ? "后端未开放此运行方式" : "请先选择至少一个技能")));
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
    $("btnTheme").textContent = theme === "dark" ? "浅色" : "深色";
    $("btnTheme").setAttribute("aria-pressed", String(theme === "dark"));
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
  state.collapsed = true;
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

function rerenderAll(settings: SettingsDTO): void {
  renderChapterStage();
  recommendChallenges(); // 按关卡推荐 Boss/传家宝（展示默认）
  const cjb = asString(settings.cjb_boss); // 持久化选择压过推荐展示
  const boss = asString(settings.sgzx_boss);
  if (cjb) state.cjb = cjb;
  if (boss) state.boss = boss;
  renderBuilds();
  renderBonds();
  renderPrestige();
  renderTeamRules();
  renderNegatives();
  refreshSummary(); // 内含 renderLaunchSummary
}

let lastAppliedSnapshotSeq = 0;

export function applySnapshot(snap: SnapshotDTO): void {
  // 必须先检查 snapshot_seq stale gate，抛弃过时快照，再更新 settings_revision
  if (snap.snapshot_seq && snap.snapshot_seq <= lastAppliedSnapshotSeq) return;
  if (snap.snapshot_seq) lastAppliedSnapshotSeq = snap.snapshot_seq;
  if (snap.settings_revision !== undefined) {
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
      const basicNames = ["法术", "急速", "魔能", "魔术", "箭术", "战术", "暴击", "固守", "陷阵"];
      state.adv = restoredAdv;
      state.advDraft = restoredAdv.slice();
      state.basic = new Set(basicNames.filter((name) => savedCards.includes(name)));
      if (Array.isArray(snap.strategy.bonds)) {
        state.growth = new Set(snap.strategy.bonds);
      }
      state.bondSaved = true;
      if (Array.isArray(snap.strategy.attributes)) {
        settings.attributes = snap.strategy.attributes;
        state.attr = new Set(snap.strategy.attributes);
      }
      if (snap.strategy.merchant) {
        settings.merchant_enabled = snap.strategy.merchant.enabled;
      }
      if (snap.strategy.treasure?.negative_allowlist) {
        settings.treasure_allow_negative = snap.strategy.treasure.negative_allowlist;
        state.negative = new Set(snap.strategy.treasure.negative_allowlist);
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
    applyBuildAndSkills(settings);
    const roomName = asString(settings.room_name);
    const roomPassword = asString(settings.room_password);
    if (roomName !== null) ($("roomName") as HTMLInputElement).value = roomName;
    if (roomPassword !== null) ($("roomPass") as HTMLInputElement).value = roomPassword;
    rerenderAll(settings);
    applyLaunchability();
  } finally {
    applying = false;
  }
}

// ---------------------------------------------------------------- 运行态信号

function applyRunStatus(run: RunStatusDTO): void {
  runActive = ACTIVE_RUN_STATES.has(run.state);
  const label = RUN_STATE_LABELS[run.state] ?? run.state;
  $("statusPill").innerHTML = `<span class="dot"></span>${escText(label)}${run.phase ? " · " + escText(run.phase) : ""}`;
  const loadBar = $("loadBar");
  loadBar.classList.toggle("show", runActive);
  loadBar.setAttribute("aria-hidden", runActive ? "false" : "true");
  $("gamesToday").textContent = String(Math.max(0, Number(run.game_count) || 0));
  $("gamesCap").textContent = run.cycle_num > 0 ? String(run.cycle_num) : "手动";
  const btnStart = $("btnStart") as HTMLButtonElement;
  if (runActive) {
    btnStart.textContent = run.state === "STOPPING" ? "停止中…" : "停止运行";
    btnStart.classList.add("stop");
    btnStart.disabled = run.state === "STOPPING";
  } else {
    btnStart.classList.remove("stop");
    refreshSummary(); // 恢复“开始运行”文案与可用性判定
    applyLaunchability();
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

function ensureRunLogPanel(): HTMLElement {
  if (runLogEl) return runLogEl;
  runLogEl = document.createElement("div");
  runLogEl.id = "odRunLog";
  runLogEl.setAttribute("aria-hidden", "true"); // 徽标已承载状态播报，日志纯视觉尾窗
  // 运行日志尾窗：运行时注入的最小展示面，不改 OD12 DOM/CSS 源；pointer-events 关闭避免挡交互。
  runLogEl.style.cssText =
    "position:absolute;left:12px;bottom:56px;z-index:8;max-width:70%;pointer-events:none;" +
    "font-size:11px;line-height:1.55;color:var(--p-ink);opacity:.78;white-space:pre-wrap;";
  $("scene-app").appendChild(runLogEl);
  return runLogEl;
}

function appendRunLog(text: string, level: string): void {
  console.log(`[run][${level}] ${text}`);
  const panel = ensureRunLogPanel();
  const line = document.createElement("div");
  line.textContent = `[${level}] ${text}`;
  if (level === "error" || level === "critical") line.style.color = "var(--p-danger)";
  panel.appendChild(line);
  while (panel.childElementCount > LOG_TAIL_LINES) panel.removeChild(panel.firstChild as ChildNode);
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
  afterGlobalCall("renderSkillRank", pushSkills);
  // 羁绊配置按用户显式点击“保存羁绊”落盘，避免每次重绘都产生一次配置请求。
  afterGlobalCall("renderNegatives", pushNegatives);
  afterGlobalCall("refreshSummary", applyLaunchability);
  afterGlobalCall("setScene", () => {
    syncWindowLayout(String(state.scene));
    const modeId = SCENE_TO_MODE_ID[state.scene];
    if (modeId) pushShell({ selected_mode_id: modeId });
  });

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


  // 主题。
  $("btnTheme").addEventListener("click", () =>
    defer(() => pushShell({ theme: state.theme === "dark" ? "dark" : "light" })),
  );

  // 配对码与接管预案。
  $("followPairForm").addEventListener("submit", () =>
    defer(() => pushConfig({ follow_pair_code: String(state.teamRules.follow.pairCode ?? "") })),
  );
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
    const { createMockBridge } = await import("./bridge/mockBridge");
    bridge = createMockBridge();
  } else {
    const { createQtBridge } = await import("./bridge/qtBridge");
    const conn = await createQtBridge();
    bridge = conn.bridge;
    wireSignals(conn.signals);
  }
  wireIntents();
  applySnapshot(await bridge.get_snapshot());
}

boot().catch(showFatal);
