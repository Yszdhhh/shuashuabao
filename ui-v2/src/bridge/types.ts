// 桥接契约唯一事实源（设计规格 §6.2）。Python 侧 DashboardFacade 结构一一对应。

/** Settings.asdict() − PERSIST_DENYLIST，全字段；字段集由 Python Settings 定义。 */
export interface SettingsDTO {
  [field: string]: unknown;
}

export interface RpcResponse {
  ok: boolean;
  request_id: string | null;
  settings_revision: number;
  snapshot_seq: number;
}

export interface StrategyDTO {
  skills: string[];
  bonds: ("祝福" | "成长" | "经济" | "贪婪" | "挑战")[];
  attributes: ("int" | "str" | "agi")[];
  merchant: { enabled: boolean; max_rerolls: number; gold_reserve: number };
  treasure: { negative_allowlist: string[] };
}

export type ConfigPatch = Partial<SettingsDTO> & {
  request_id?: string;
  settings_revision?: number;
  strategy?: Partial<StrategyDTO>;
};

export interface ShellDTO {
  theme: "light" | "dark";
  selected_mode_id: string;
}

export interface ModeDTO {
  id: string;
  label: string;
  /** desktop_may_start(id)：布尔判定，证据不作门禁。 */
  startable: boolean;
  /** live_partial | video_detail_no_click | skeleton | live_cli */
  evidence_status: string;
  /** badge_text(spec) */
  badge: string;
  /** 不可启动时的原因，可空 */
  blocked_reason: string;
  visible_settings: string[];
}

export type RunState =
  | "IDLE"
  | "STARTING"
  | "RUNNING"
  | "STOPPING"
  | "COMPLETE"
  | "FAILED";

export interface RunStatusDTO {
  state: RunState;
  mode_id: string | null;
  phase: string;
  game_count: number;
  cycle_num: number;
  terminal_reason: string;
  ocr_status: string;
  last_action: string;
}

export interface PreflightCheck {
  /** mode_enabled / live_lock / skills_non_empty / cycle_valid / follow_pair_code */
  id: string;
  ok: boolean;
  detail: string;
}

export interface PreflightDTO extends RpcResponse {
  blocked_reason: string;
  checks: PreflightCheck[];
}

export interface SnapshotDTO {
  request_id: string | null;
  settings_revision: number;
  snapshot_seq: number;
  settings: SettingsDTO;
  strategy: StrategyDTO;
  shell: ShellDTO;
  modes: ModeDTO[];
  run: RunStatusDTO;
}

export interface ConfigPatchResult extends RpcResponse {
  errors: string[];
  settings: SettingsDTO;
  strategy: StrategyDTO;
}

export interface ShellPatchResult extends RpcResponse {
  errors: string[];
  shell: ShellDTO;
}

export interface RunResult extends RpcResponse {
  error?: string;
}

/**
 * DashboardFacade 白名单方法面（QWebChannel 唯一注册对象）。
 * 全部方法入参出参均为 JSON 字符串；此处以 DTO 类型表达语义。
 */
export interface DashboardBridge {
  get_snapshot(): Promise<SnapshotDTO>;
  update_config(patch: ConfigPatch): Promise<ConfigPatchResult>;
  update_shell(patch: Partial<ShellDTO>): Promise<ShellPatchResult>;
  validate_preflight(mode_id: string): Promise<PreflightDTO>;
  start_run(mode_id: string): Promise<RunResult>;
  stop_run(): Promise<RunResult>;
  window_control(action: "minimize" | "close"): Promise<RpcResponse>;
}

/** QWebChannel 自动暴露的 Qt Signals（JS signal.connect(...)）。 */
export interface DashboardBridgeSignals {
  snapshot_changed: { connect(cb: (json: string) => void): void };
  run_status_changed: { connect(cb: (json: string) => void): void };
  log_appended: { connect(cb: (text: string, level: string) => void): void };
}
