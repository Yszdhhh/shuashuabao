// 桥接契约唯一事实源（设计规格 §6.2）。Python 侧 DashboardFacade 结构一一对应。

export interface SettingsDTO {
  skills?: string[];
  cards?: string[];
  bond_scheme?: string;
  bond_must_take?: string[];
  bonds?: ("祝福" | "成长" | "经济" | "贪婪" | "挑战")[];
  attributes?: ("int" | "str" | "agi")[];
  merchant_enabled?: boolean;
  merchant_max_rerolls?: number;
  merchant_gold_reserve?: number;
  treasure_allow_negative?: string[];
  auto_secret_realm?: boolean;
  auto_close_main_line?: boolean;
  auto_archaeology?: boolean;
  new_room_every_times?: boolean;
  find_longzhu_where_multi_game?: boolean;
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
  cards?: string[];
  attributes: ("int" | "str" | "agi")[];
  merchant?: { enabled?: boolean; max_rerolls?: number; gold_reserve?: number };
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
  startable: boolean;
  evidence_status: string;
  badge: string;
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

export type UnsubscribeFn = () => void;

export interface DashboardBridge {
  get_snapshot(): Promise<SnapshotDTO>;
  update_config(patch: ConfigPatch): Promise<ConfigPatchResult>;
  update_shell(patch: Partial<ShellDTO>): Promise<ShellPatchResult>;
  validate_preflight(mode_id: string): Promise<PreflightDTO>;
  start_run(mode_id: string, expectedRevision?: number): Promise<RunResult>;
  stop_run(): Promise<RunResult>;
  window_control(action: "minimize" | "close"): Promise<RpcResponse>;
}

export interface DashboardBridgeSignals {
  snapshot_changed: {
    connect(cb: (json: string) => void): void;
    disconnect?(cb: (json: string) => void): void;
  };
  run_status_changed: {
    connect(cb: (json: string) => void): void;
    disconnect?(cb: (json: string) => void): void;
  };
  log_appended: {
    connect(cb: (text: string, level: string) => void): void;
    disconnect?(cb: (text: string, level: string) => void): void;
  };
}
