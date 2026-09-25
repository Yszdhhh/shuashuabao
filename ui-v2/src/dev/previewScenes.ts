// 开发/预览专用：场景预览条的动作表（UI-24）。
// 只在 main.ts 的非 production 分支动态导入，正式构建不会打包进来。
// 使用方：
//   1. 桌面「刷刷宝 UI预览（不连接游戏）」Qt 窗口：旁边的场景面板调用 window.__sbPreview.run(id)，
//      并监听控制台里的 [sb-preview-layout] 行来模拟正式宿主的窗口尺寸。
//   2. 在线预览沙盒（claude.ai Artifact）：外层框架的场景条调用同一个 window.__sbPreview.run(id)。
// 所有动作只调用看板页面里已有的全局函数，不改业务逻辑；数据全部是模拟值。

type AnyFn = (...args: unknown[]) => unknown;
type PreviewState = Record<string, unknown> & {
  modal?: string;
  running?: boolean;
  scene?: string;
  bondSaved?: boolean;
  adv?: string[];
  advDraft?: string[];
};

export interface PreviewScene {
  id: string;
  group: "模式" | "流程" | "弹层" | "数据";
  label: string;
}

export const PREVIEW_SCENES: PreviewScene[] = [
  { id: "farm", group: "模式", label: "单刷" },
  { id: "hitch", group: "模式", label: "蹭车 · 小窗" },
  { id: "lead", group: "模式", label: "带车" },
  { id: "follow", group: "模式", label: "跟车 · 小窗" },
  { id: "boot", group: "流程", label: "启动过场" },
  { id: "preflight", group: "流程", label: "预检中" },
  { id: "preflightFail", group: "流程", label: "预检失败" },
  { id: "running", group: "流程", label: "运行中" },
  { id: "doneHitch", group: "流程", label: "完成 · 蹭车统计" },
  { id: "doneSolo", group: "流程", label: "完成 · 单刷" },
  { id: "interrupted", group: "流程", label: "中断" },
  { id: "subscription", group: "弹层", label: "订阅激活" },
  { id: "activated", group: "弹层", label: "激活成功" },
  { id: "rep", group: "弹层", label: "声望挑战" },
  { id: "cjb", group: "弹层", label: "传家宝" },
  { id: "boss", group: "弹层", label: "Boss" },
  { id: "drawer", group: "弹层", label: "高级设置" },
  { id: "log", group: "弹层", label: "运行日志" },
  { id: "bondEdit", group: "弹层", label: "编辑羁绊" },
  { id: "adv0", group: "数据", label: "高级卡组 0 个" },
  { id: "adv2", group: "数据", label: "高级卡组 2 个" },
  { id: "adv5", group: "数据", label: "高级卡组 5 个" },
  { id: "themeDark", group: "数据", label: "深色" },
  { id: "themeLight", group: "数据", label: "浅色" },
];

const w = window as unknown as Record<string, unknown>;
const fn = (name: string): AnyFn => {
  const f = w[name];
  if (typeof f !== "function") throw new Error(`看板页面缺少 ${name}()，预览动作无法执行`);
  return f as AnyFn;
};
const st = (): PreviewState => {
  const get = w.__sbPreviewState;
  return typeof get === "function" ? ((get as () => PreviewState)() || {}) : {};
};
const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const $ = (id: string) => document.getElementById(id);

const MOCK_SUB = { active: true, status: "正常", expires_at: "2026-10-23", live_authorized: true, live_status: "LIVE 已授权" };
const HITCH_SUMMARY = {
  available: true,
  duration_seconds: 2 * 3600 + 14 * 60,
  hitch: { started: 21, completed: 20, success: 18, failure: 2, stages: { "2-7": 12, "1-21": 8 } },
  solo: { completed: 3, success: 3, failure: 0 },
};

function cleanup(): void {
  try { if (st().modal) fn("closeModal")(); } catch { /* 没有打开的弹层 */ }
  try { fn("setDrawer")(false); } catch { /* 抽屉不存在 */ }
  document.querySelectorAll(".sb-done-veil, .sb-pre-veil, .sb-act, .sb-boot").forEach((n) => n.remove());
  const strip = $("sbLogStrip");
  if (strip && strip.classList.contains("open")) $("sbLogToggle")?.click();
  const s = st();
  if (s.bondSaved === false) { s.bondSaved = true; try { fn("renderBonds")(); } catch { /* ignore */ } }
}

async function toFarm(): Promise<void> {
  if (st().running) { ($("btnStart") as HTMLButtonElement | null)?.click(); await wait(900); }
  if (st().scene !== "farm") { fn("setScene")("farm"); await wait(250); }
}

function ensureSubscription(): void {
  const ok = w.isSubscriptionOk;
  if (typeof ok === "function" && !(ok as () => boolean)()) fn("applySubscription")(MOCK_SUB);
}

function setAdv(ids: string[]): void {
  const s = st();
  s.adv = ids.slice();
  s.advDraft = ids.slice();
  s.bondSaved = true;
  fn("renderBonds")();
}

function setTheme(theme: "dark" | "light"): void {
  document.body.dataset.theme = theme;
  document.querySelectorAll<HTMLElement>(".win").forEach((el) => { el.dataset.theme = theme; });
}

const ACTIONS: Record<string, () => Promise<void> | void> = {
  farm: () => toFarm(),
  hitch: async () => { await toFarm(); fn("setScene")("hitch"); },
  lead: async () => { await toFarm(); fn("setScene")("lead"); },
  follow: async () => { await toFarm(); fn("setScene")("follow"); },
  boot: () => { fn("showBootSplash")("preview"); },
  preflight: async () => { await toFarm(); fn("showPreflight")({ fast: true }); await wait(900); fn("preflightStage")("accepted"); },
  preflightFail: async () => { await toFarm(); fn("showPreflight")({ fast: true }); await wait(700); fn("preflightStage")("fail", "订阅未激活，请先激活卡密"); },
  running: async () => { await toFarm(); ensureSubscription(); await wait(200); ($("btnStart") as HTMLButtonElement | null)?.click(); },
  doneHitch: () => { fn("showRunComplete")({ preview: true, games: 20, modeId: "lobby_hitch", summary: HITCH_SUMMARY }); },
  doneSolo: () => {
    fn("showRunComplete")({ preview: true, games: 100, modeId: "normal_farm", duration: (5 * 3600 + 32 * 60) * 1000, summary: { available: true, solo: { completed: 100, success: 97, failure: 3 } } });
  },
  interrupted: () => { fn("showRunComplete")({ preview: true, interrupted: true, games: 7, modeId: "normal_farm", duration: 41 * 60 * 1000, summary: { available: false } }); },
  subscription: () => { fn("openSubscriptionModal")(); },
  activated: () => { ensureSubscription(); fn("playActivation")({ status: "正常", expires_at: "2026-10-23", live_status: "LIVE 已授权" }); },
  rep: async () => { await toFarm(); fn("openModal")("rep"); },
  cjb: () => { fn("openModal")("cjb"); },
  boss: () => { fn("openModal")("boss"); },
  drawer: async () => { await toFarm(); fn("setDrawer")(true); },
  log: () => { $("sbLogToggle")?.click(); },
  bondEdit: async () => { await toFarm(); $("btnEditBonds")?.click(); },
  adv0: async () => { await toFarm(); setAdv([]); },
  adv2: async () => { await toFarm(); setAdv(["daodao", "haidao"]); },
  adv5: async () => { await toFarm(); setAdv(["daodao", "yihuo", "dasheng", "xiuxian", "fengshen"]); },
  themeDark: () => setTheme("dark"),
  themeLight: () => setTheme("light"),
};

export async function runPreviewScene(id: string): Promise<void> {
  const action = ACTIONS[id];
  if (!action) throw new Error(`未知预览场景：${id}`);
  if (!id.startsWith("theme")) cleanup();
  await action();
}

export function installPreviewScenes(): void {
  w.__sbPreview = { scenes: PREVIEW_SCENES, run: runPreviewScene };
  // 宿主窗口尺寸：mock 桥广播 sb:window-layout；这里转成一行控制台日志，
  // 桌面 Qt 预览窗口据此把自己缩成正式宿主的尺寸（看板 960×820 / 小窗 360×实测高）。
  window.addEventListener("sb:window-layout", (e) => {
    const detail = (e as CustomEvent<{ layout: string; height?: number }>).detail || { layout: "dashboard" };
    console.info(`[sb-preview-layout] ${JSON.stringify(detail)}`);
  });
}
