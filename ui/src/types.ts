export interface AppSettings {
  stage1: number;
  stage2: number;
  room_name: string;
  room_password: string;
  new_room_every_times: boolean;
  query_timeout: number;
  game_timeout: number;
  game_mode: number; // 0 = 自己刷图
  dragon_ball_count: number;
  find_longzhu_where_multi_game: boolean;
  auto_secret_realm: boolean;
  auto_close_main_line: boolean;
  close_main_line_time: number;
  auto_clean_interval: number;
  auto_card: boolean;
  auto_weapon: boolean;
  damage_increase_card: boolean;
  develop_priority: boolean;
  develop_time: number;
  auto_reputation: boolean;
  continue_reputation: boolean;
  reputation_stage1: number;
  reputation_stage2: number;
  reputation_cjb_boss: string;
  reputation_sgzx_boss: string;
  cjb_boss: string;
  sgzx_boss: string;
  skills: string[];
  cards: string[];
  boss_live_time: number;
  kill_boss_num: number;
  cycle_num: number;
  archive_boss_time: number;
  treasure_num: number;
  auto_gambling_time: number;
  match_threshold: number;
  click_delay_ms: number;
  loop_sleep_ms: number;
  window_title_contains: string;
  window_size: [number, number];
  images_dir: string;
  dry_run: boolean;
}

export interface SkillOption {
  code: string;
  image_url: string | null;
}

export interface BossOption {
  name: string;
  image_url: string;
}

export interface BossesResponse {
  main: BossOption[];
  cjb: BossOption[];
}

export interface CardOption {
  name: string;
  image_url: string;
}

export interface RunStatus {
  running: boolean;
  phase: string;
  phase_name: string;
  game_count: number;
  last_error: string | null;
  log_count: number;
}

export interface LogItem {
  id: number;
  time: string;
  text: string;
  type: 'info' | 'error' | 'warn';
}
