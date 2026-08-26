import { describe, expect, it } from "vitest";
import { createMockBridge } from "../src/bridge/mockBridge";
import type { ModeDTO, RunStatusDTO, SnapshotDTO } from "../src/bridge/types";

const RUN_STATES = ["IDLE", "STARTING", "RUNNING", "STOPPING", "COMPLETE", "FAILED"];
const MODE_KEYS: (keyof ModeDTO)[] = [
  "id", "label", "startable", "evidence_status", "badge", "blocked_reason", "visible_settings",
];
const RUN_KEYS: (keyof RunStatusDTO)[] = [
  "state", "mode_id", "phase", "game_count", "cycle_num", "terminal_reason", "ocr_status", "last_action",
];
const CHECK_IDS = ["mode_enabled", "live_lock", "skills_non_empty", "cycle_valid", "follow_pair_code"];

describe("mockBridge 形状契约", () => {
  it("get_snapshot 返回与 types.ts 一致的 SnapshotDTO", async () => {
    const bridge = createMockBridge();
    const snap: SnapshotDTO = await bridge.get_snapshot();

    expect(snap.settings).toBeTypeOf("object");
    expect(["light", "dark"]).toContain(snap.shell.theme);
    expect(typeof snap.shell.selected_mode_id).toBe("string");
    expect(Array.isArray(snap.modes)).toBe(true);
    expect(snap.modes.map((mode) => mode.id)).toEqual([
      "normal_farm", "follow_team", "gambling_wood", "raid_wait", "lobby_hitch", "lab",
    ]);
    for (const mode of snap.modes) {
      expect(Object.keys(mode).sort()).toEqual([...MODE_KEYS].sort());
      expect(typeof mode.startable).toBe("boolean");
    }
    expect(Object.keys(snap.run).sort()).toEqual([...RUN_KEYS].sort());
    expect(RUN_STATES).toContain(snap.run.state);
  });

  it("validate_preflight 返回五项 check 行且聚合 ok", async () => {
    const bridge = createMockBridge();
    const pf = await bridge.validate_preflight("lobby_hitch");
    expect(pf.checks.map((c) => c.id)).toEqual(CHECK_IDS);
    for (const c of pf.checks) {
      expect(typeof c.detail).toBe("string");
      expect(typeof c.ok).toBe("boolean");
    }
    expect(pf.ok).toBe(pf.checks.every((c) => c.ok));
    expect(pf.ok).toBe(false); // mode 可启动，但默认 mock 技能预检仍故意失败
  });

  it("update_config 往返保留补丁字段", async () => {
    const bridge = createMockBridge();
    const res = await bridge.update_config({ cycle: 3 });
    expect(res.ok).toBe(true);
    expect(res.errors).toEqual([]);
    expect((await bridge.get_snapshot()).settings.cycle).toBe(3);
  });
});
