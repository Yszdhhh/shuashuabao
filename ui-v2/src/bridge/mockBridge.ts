// 仅 Vite dev / 浏览器测试使用：形状与 types.ts 完全一致的诚实假数据。
// 生产构建不打包（见 main.ts 的 MODE 分支）；禁止被生产 Python/QWebEngine 代码引用。
import type {
  DashboardBridge,
  ModeDTO,
  RunStatusDTO,
  SettingsDTO,
  ShellDTO,
  SnapshotDTO,
} from "./types";

const MODES: ModeDTO[] = [
  {
    id: "normal_farm",
    label: "自己刷图",
    startable: true,
    evidence_status: "live_partial",
    badge: "可启动",
    blocked_reason: "",
    visible_settings: [
      "stage_targets", "auto_reputation", "reputation_type", "reputation_level",
      "skills", "cards", "treasure_allow_negative", "auto_secret_realm", "dry_run",
    ],
  },
  {
    id: "follow_team",
    label: "跟车",
    startable: true,
    evidence_status: "skeleton",
    badge: "可启动",
    blocked_reason: "",
    visible_settings: ["follow_cycle_num", "follow_after_room", "follow_pair_code", "dry_run"],
  },
  {
    id: "gambling_wood",
    label: "赌木",
    startable: false,
    evidence_status: "skeleton",
    badge: "待验证 · 不可启动",
    blocked_reason: "赌木 未开放 live",
    visible_settings: ["stage_targets", "treasure_num"],
  },
  {
    id: "raid_wait",
    label: "站团本",
    startable: false,
    evidence_status: "skeleton",
    badge: "待验证 · 不可启动",
    blocked_reason: "站团本 未开放 live",
    visible_settings: ["dry_run"],
  },
  {
    id: "lobby_hitch",
    label: "大厅找房蹭车",
    startable: true,
    evidence_status: "video_detail_no_click",
    badge: "可启动",
    blocked_reason: "",
    visible_settings: [
      "hitch_stage_prefix", "hitch_cycle_num", "hitch_after_goal", "skip_password_rooms",
      "refresh_s", "never_quick_join", "hitch_reject_list", "dry_run",
    ],
  },
  {
    id: "lab",
    label: "实验室",
    startable: false,
    evidence_status: "live_cli",
    badge: "CLI",
    blocked_reason: "实验室 未开放桌面入口",
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
    room_name: "",
    room_password: "",
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
  return {
    request_id: null,
    settings_revision: 0,
    snapshot_seq: 1,
    settings,
    strategy: {
      skills: ["asj", "asjg", "assx", "jq"],
      bonds: ["祝福", "成长", "经济", "贪婪", "挑战"],
      attributes: [],
      merchant: { enabled: false, max_rerolls: 0, gold_reserve: 0 },
      treasure: { negative_allowlist: [] },
    },
    shell,
    modes: MODES.map((m) => ({ ...m })),
    run: { ...RUN },
  };
}

function preflight(mode_id: string) {
  const mode = MODES.find((m) => m.id === mode_id);
  const checks = [
    {
      id: "mode_enabled",
      ok: Boolean(mode?.startable),
      detail: mode?.startable ? "已验证可启动" : (mode?.blocked_reason || `未知模式 ${mode_id}`),
    },
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
      const { request_id = null, settings_revision: _expected, strategy, ...settingsPatch } = patch;
      current = {
        ...current,
        request_id,
        settings_revision: current.settings_revision + 1,
        snapshot_seq: current.snapshot_seq + 1,
        settings: { ...current.settings, ...settingsPatch },
        strategy: strategy
          ? {
              ...current.strategy,
              ...strategy,
              merchant: { ...current.strategy.merchant, ...(strategy.merchant || {}) },
              treasure: { ...current.strategy.treasure, ...strategy.treasure },
            }
          : current.strategy,
      };
      return {
        ok: true,
        request_id,
        settings_revision: current.settings_revision,
        snapshot_seq: current.snapshot_seq,
        errors: [],
        settings: { ...current.settings },
        strategy: { ...current.strategy },
      };
    },
    async update_shell(patch) {
      current = {
        ...current,
        snapshot_seq: current.snapshot_seq + 1,
        shell: { ...current.shell, ...patch },
      };
      return {
        ok: true,
        request_id: null,
        settings_revision: current.settings_revision,
        snapshot_seq: current.snapshot_seq,
        errors: [],
        shell: { ...current.shell },
      };
    },
    async validate_preflight(mode_id) {
      return {
        ...preflight(mode_id),
        request_id: null,
        settings_revision: current.settings_revision,
        snapshot_seq: current.snapshot_seq,
      };
    },
    async start_run() {
      return {
        ok: false, request_id: null, settings_revision: current.settings_revision,
        snapshot_seq: current.snapshot_seq, error: "mockBridge 不执行真实运行",
      };
    },
    async stop_run() {
      return { ok: true, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq };
    },
    async window_control() {
      return { ok: true, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq };
    },
    async set_window_layout() {
      return { ok: true, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq };
    },
    async activate_subscription() {
      return { ok: true, message: "测试卡密激活成功", status: "正常", expires_at: "2026-09-30" };
    },
  };
}
