// 仅 Vite dev / 浏览器测试使用：形状与 types.ts 完全一致的诚实假数据。
// 生产构建不打包（见 main.ts 的 MODE 分支）；禁止被生产 Python/QWebEngine 代码引用。
import type {
  DashboardBridge,
  ModeDTO,
  PreflightDTO,
  RunStatusDTO,
  SettingsDTO,
  ShellDTO,
  SnapshotDTO,
} from "./types";

const MODES: ModeDTO[] = [
  {
    id: "solo",
    label: "单人刷图",
    startable: true,
    evidence_status: "live_partial",
    badge: "已验证",
    blocked_reason: "",
    visible_settings: ["chapter", "stage", "cycle", "skills", "bonds"],
  },
  {
    id: "lead",
    label: "带车",
    startable: true,
    evidence_status: "live_partial",
    badge: "已验证",
    blocked_reason: "",
    visible_settings: ["chapter", "stage", "cycle", "skills", "team_rules"],
  },
  {
    id: "follow",
    label: "跟车",
    startable: true,
    evidence_status: "video_detail_no_click",
    badge: "视频验证",
    blocked_reason: "",
    visible_settings: ["team_rules", "pair_code"],
  },
  {
    id: "hitch",
    label: "蹭车",
    startable: false,
    evidence_status: "skeleton",
    badge: "待验证",
    blocked_reason: "蹭车只搜房，不能点火",
    visible_settings: ["team_rules"],
  },
  {
    id: "lab",
    label: "实验室",
    startable: false,
    evidence_status: "skeleton",
    badge: "骨架",
    blocked_reason: "实验模式未接入 RunnerService",
    visible_settings: [],
  },
];

const RUN: RunStatusDTO = {
  state: "IDLE",
  mode_id: null,
  phase: "",
  game_count: 0,
  cycle_num: 0,
  terminal_reason: "",
  ocr_status: "ok",
  last_action: "",
};

function snapshot(): SnapshotDTO {
  // 字段与 Python DashboardFacade.get_snapshot 一致（SettingsDTO 真实键名），
  // 让 dev/浏览器预览同样走 main.ts 的快照初始化路径。
  const settings: SettingsDTO = {
    mode_id: "normal_farm",
    cycle_num: 100,
    follow_cycle_num: 100,
    hitch_cycle_num: 100,
    follow_after_room: "solo",
    hitch_after_goal: "solo",
    follow_pair_code: "",
    stage_targets: ["1-10"],
    skills: ["asj", "asjg", "assx", "jq"],
    skill_priority: ["asj", "asjg", "assx", "jq"],
    skill_custom_routes: {},
    auto_secret_realm: false,
    auto_close_main_line: false,
    auto_archaeology: false,
    new_room_every_times: false,
    find_longzhu_where_multi_game: true,
    auto_reputation: true,
    reputation_allocations: {},
    cjb_boss: "",
    sgzx_boss: "",
  };
  const shell: ShellDTO = { theme: "light", selected_mode_id: "normal_farm" };
  return { settings, shell, modes: MODES.map((m) => ({ ...m })), run: { ...RUN } };
}

function preflight(mode_id: string): PreflightDTO {
  const mode = MODES.find((m) => m.id === mode_id);
  const checks = [
    { id: "mode_enabled", ok: Boolean(mode?.startable), detail: mode ? "" : `未知模式 ${mode_id}` },
    { id: "live_lock", ok: true, detail: "无运行锁" },
    { id: "skills_non_empty", ok: false, detail: "尚未选择技能" },
    { id: "cycle_valid", ok: true, detail: "循环次数有效" },
    { id: "follow_pair_code", ok: true, detail: "配对码长度合法" },
  ];
  return {
    ok: checks.every((c) => c.ok),
    blocked_reason: checks.every((c) => c.ok) ? "" : "预检未通过",
    checks,
  };
}

export function createMockBridge(): DashboardBridge {
  let current = snapshot();
  return {
    async get_snapshot() {
      return current;
    },
    async update_config(patch) {
      current = { ...current, settings: { ...current.settings, ...patch } };
      return { ok: true, errors: [], settings: { ...current.settings } };
    },
    async update_shell(patch) {
      current = { ...current, shell: { ...current.shell, ...patch } };
      return { ok: true, errors: [], shell: { ...current.shell } };
    },
    async validate_preflight(mode_id) {
      return preflight(mode_id);
    },
    async start_run() {
      return { ok: false, error: "mockBridge 不执行真实运行" };
    },
    async stop_run() {
      return { ok: true };
    },
    async window_control() {
      return { ok: true };
    },
  };
}
