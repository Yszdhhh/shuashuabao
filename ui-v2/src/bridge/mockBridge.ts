// 仅 Vite dev / 浏览器测试使用：形状与 types.ts 完全一致的诚实假数据。
// 生产构建不打包（见 main.ts 的 MODE 分支）；禁止被生产 Python/QWebEngine 代码引用。
import type {
  BridgeInfoDTO,
  DashboardBridge,
  ModeDTO,
  RunStatusDTO,
  SettingsDTO,
  ShellDTO,
  SnapshotDTO,
} from "./types";

/** Failure switches used by browser/dev tests to exercise the same lifecycle
 * branches as the production facade without maintaining a second fake FSM. */
export interface MockBridgeOptions {
  subscriptionAllowed?: boolean;
  runtimeRootReady?: boolean;
  ocrReady?: boolean;
  targetWindowReady?: boolean;
  uipiReady?: boolean;
  buildIdentityReady?: boolean;
  startFailure?: string;
}

const MODES: ModeDTO[] = [
  {
    id: "normal_farm",
    label: "自己刷图",
    startable: true,
    evidence_status: "live_partial",
    current_evidence: { status: "MISSING", reason: "开发桥未绑定真实构建证据" },
    badge: "可启动",
    blocked_reason: "",
    visible_settings: [
      "stage_targets", "auto_reputation", "reputation_type", "reputation_level",
      "skills", "cards", "treasure_allow_negative", "cjb_boss", "sgzx_boss",
      "auto_secret_realm", "dry_run",
    ],
  },
  {
    id: "follow_team",
    label: "跟车",
    startable: true,
    evidence_status: "skeleton",
    current_evidence: { status: "MISSING", reason: "开发桥未绑定真实构建证据" },
    badge: "可启动",
    blocked_reason: "",
    visible_settings: ["follow_cycle_num", "follow_after_room", "follow_pair_code", "dry_run"],
  },
  {
    id: "gambling_wood",
    label: "赌木",
    startable: false,
    evidence_status: "skeleton",
    current_evidence: { status: "MISSING", reason: "开发桥未绑定真实构建证据" },
    badge: "待验证 · 不可启动",
    blocked_reason: "赌木 未开放 live",
    visible_settings: ["stage_targets", "treasure_num"],
  },
  {
    id: "raid_wait",
    label: "站团本",
    startable: false,
    evidence_status: "skeleton",
    current_evidence: { status: "MISSING", reason: "开发桥未绑定真实构建证据" },
    badge: "待验证 · 不可启动",
    blocked_reason: "站团本 未开放 live",
    visible_settings: ["dry_run"],
  },
  {
    id: "lobby_hitch",
    label: "大厅找房蹭车",
    startable: true,
    evidence_status: "video_detail_no_click",
    current_evidence: { status: "MISSING", reason: "开发桥未绑定真实构建证据" },
    badge: "可启动",
    blocked_reason: "",
    visible_settings: [
      "hitch_stage_prefix", "hitch_rotate_interval", "hitch_cycle_num", "hitch_after_goal",
      "cjb_boss", "sgzx_boss", "skip_password_rooms",
      "refresh_s", "never_quick_join", "hitch_reject_list", "dry_run",
    ],
  },
  {
    id: "lab",
    label: "实验室",
    startable: false,
    evidence_status: "live_cli",
    current_evidence: { status: "MISSING", reason: "开发桥未绑定真实构建证据" },
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
    hitch_stage_prefix: "4,3",
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

function preflight(mode_id: string, settings: SettingsDTO, options: MockBridgeOptions) {
  const mode = MODES.find((m) => m.id === mode_id);
  const skills = Array.isArray(settings.skills) ? settings.skills.filter(Boolean) : [];
  const cycle = mode_id === "follow_team"
    ? Number(settings.follow_cycle_num)
    : mode_id === "lobby_hitch"
    ? Number(settings.hitch_cycle_num)
    : Number(settings.cycle_num);
  const checks = [
    {
      id: "mode_enabled",
      ok: Boolean(mode?.startable),
      detail: mode?.startable ? "已验证可启动" : (mode?.blocked_reason || `未知模式 ${mode_id}`),
    },
    { id: "live_lock", ok: true, detail: "无运行锁" },
    { id: "skills_non_empty", ok: skills.length >= 1 && skills.length <= 4, detail: skills.length ? `技能 ${skills.length} 个` : "技能为空" },
    { id: "cycle_valid", ok: Number.isInteger(cycle) && cycle >= 0, detail: Number.isInteger(cycle) && cycle >= 0 ? `循环次数 ${cycle}` : "循环次数非法" },
    { id: "follow_pair_code", ok: String(settings.follow_pair_code || "").length <= 24, detail: "配对码长度合法" },
    { id: "subscription", ok: options.subscriptionAllowed !== false, detail: options.subscriptionAllowed === false ? "开发桥模拟订阅拒绝" : "开发桥模拟订阅通过" },
    { id: "runtime_root", ok: options.runtimeRootReady !== false, detail: options.runtimeRootReady === false ? "开发桥模拟运行目录不可用" : "开发桥运行目录可用" },
    { id: "ocr_runtime", ok: options.ocrReady !== false, detail: options.ocrReady === false ? "开发桥模拟 OCR 不可用" : "开发桥模拟 OCR 就绪" },
    { id: "uipi", ok: options.uipiReady !== false, detail: options.uipiReady === false ? "开发桥模拟输入权限不足" : "开发桥模拟输入权限通过" },
    { id: "target_window", ok: options.targetWindowReady !== false, detail: options.targetWindowReady === false ? "开发桥模拟目标窗口缺失" : "开发桥模拟目标窗口可用" },
    { id: "build_identity", ok: options.buildIdentityReady !== false, detail: options.buildIdentityReady === false ? "开发桥模拟构建身份不一致" : "开发桥模拟构建身份一致" },
  ];
  return {
    ok: checks.every((c) => c.ok),
    blocked_reason: checks.every((c) => c.ok) ? "" : "预检未通过",
    checks,
  };
}

export function createMockBridge(options: MockBridgeOptions = {}): DashboardBridge {
  let current = snapshot();
  return {
    async get_bridge_info(): Promise<BridgeInfoDTO> {
      return {
        ok: true,
        schema_version: 2,
        required_methods: [
          "get_bridge_info", "get_snapshot", "update_config", "update_shell",
          "validate_preflight", "start_run", "stop_run", "window_control",
          "set_window_layout", "activate_subscription",
        ],
        required_signals: ["snapshot_changed", "run_status_changed", "log_appended"],
      };
    },
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
        ...preflight(mode_id, current.settings, options),
        request_id: null,
        settings_revision: current.settings_revision,
        snapshot_seq: current.snapshot_seq,
      };
    },
    async start_run(mode_id, expectedRevision) {
      if (expectedRevision !== undefined && expectedRevision !== current.settings_revision) {
        return { ok: false, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq, error: "Settings revision mismatch" };
      }
      const pf = preflight(mode_id, current.settings, options);
      if (!pf.ok) {
        return { ok: false, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq, error: pf.blocked_reason };
      }
      if (options.startFailure) {
        current = {
          ...current,
          snapshot_seq: current.snapshot_seq + 1,
          run: {
            ...current.run,
            state: "FAILED",
            mode_id,
            phase: "ERROR",
            terminal_reason: options.startFailure,
          },
        };
        return { ok: false, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq, error: options.startFailure };
      }
      const cycle = mode_id === "follow_team"
        ? Number(current.settings.follow_cycle_num)
        : mode_id === "lobby_hitch"
        ? Number(current.settings.hitch_cycle_num)
        : Number(current.settings.cycle_num);
      current = {
        ...current,
        snapshot_seq: current.snapshot_seq + 1,
        run: {
          ...current.run,
          state: "RUNNING",
          mode_id,
          phase: "STARTING",
          cycle_num: Number.isFinite(cycle) ? cycle : 0,
          terminal_reason: "",
        },
      };
      return { ok: true, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq };
    },
    async stop_run() {
      current = {
        ...current,
        snapshot_seq: current.snapshot_seq + 1,
        run: {
          ...current.run,
          state: current.run.state === "RUNNING" || current.run.state === "STARTING" ? "COMPLETE" : current.run.state,
          phase: current.run.state === "RUNNING" || current.run.state === "STARTING" ? "COMPLETE" : current.run.phase,
          terminal_reason: current.run.state === "RUNNING" || current.run.state === "STARTING" ? "开发桥模拟停止" : current.run.terminal_reason,
        },
      };
      return { ok: true, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq };
    },
    async window_control() {
      return { ok: true, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq };
    },
    async set_window_layout() {
      return { ok: true, request_id: null, settings_revision: current.settings_revision, snapshot_seq: current.snapshot_seq };
    },
    async activate_subscription() {
      if (options.subscriptionAllowed === false) {
        return { ok: false, message: "开发桥模拟订阅拒绝", status: "未授权", expires_at: "" };
      }
      return { ok: true, message: "测试卡密激活成功", status: "正常", expires_at: "2026-09-30" };
    },
    async refresh_subscription_status() {
      if (options.subscriptionAllowed === false) {
        return { ok: false, error: "开发桥模拟订阅拒绝" };
      }
      return { ok: true, subscription: current.subscription };
    },
  };
}
