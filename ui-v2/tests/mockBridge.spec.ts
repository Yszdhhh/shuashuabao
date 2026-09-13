import { describe, expect, it, vi } from "vitest";
import { createMockBridge, createMockBridgeConnection } from "../src/bridge/mockBridge";
import type { ModeDTO, RunStatusDTO, SnapshotDTO } from "../src/bridge/types";

const RUN_STATES = ["IDLE", "STARTING", "RUNNING", "STOPPING", "COMPLETE", "FAILED"];
const MODE_KEYS: (keyof ModeDTO)[] = [
  "id", "label", "startable", "evidence_status", "current_evidence", "badge", "blocked_reason", "visible_settings",
];
const RUN_KEYS: (keyof RunStatusDTO)[] = [
  "state", "mode_id", "phase", "game_count", "cycle_num", "terminal_reason", "ocr_status", "last_action",
];
const CHECK_IDS = [
  "mode_enabled", "live_lock", "skills_non_empty", "cycle_valid", "follow_pair_code",
  "subscription", "runtime_root", "ocr_runtime", "uipi", "target_window", "build_identity",
];

describe("mockBridge 形状契约", () => {
  it("get_snapshot 返回与 types.ts 一致的 SnapshotDTO", async () => {
    const bridge = createMockBridge();
    const snap: SnapshotDTO = await bridge.get_snapshot();

    expect(snap.settings).toBeTypeOf("object");
    expect(snap).toMatchObject({ request_id: null, settings_revision: 0, snapshot_seq: 1 });
    expect(snap.strategy.merchant).toEqual({ enabled: false, max_rerolls: 0, gold_reserve: 0 });
    expect(snap.strategy.attributes).toEqual([]);
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

  it("validate_preflight 返回完整 check 行且聚合 ok", async () => {
    const bridge = createMockBridge();
    const pf = await bridge.validate_preflight("lobby_hitch");
    expect(pf.checks.map((c) => c.id)).toEqual(CHECK_IDS);
    for (const c of pf.checks) {
      expect(typeof c.detail).toBe("string");
      expect(typeof c.ok).toBe("boolean");
    }
    expect(pf.ok).toBe(pf.checks.every((c) => c.ok));
    expect(pf.ok).toBe(true); // 开发桥默认快照包含合法技能和模拟依赖
  });

  it("failure switches cover subscription/runtime readiness without changing the bridge shape", async () => {
    const bridge = createMockBridge({ subscriptionAllowed: false, ocrReady: false });
    const pf = await bridge.validate_preflight("normal_farm");
    expect(pf.ok).toBe(false);
    expect(pf.checks.find((c) => c.id === "subscription")?.ok).toBe(false);
    expect(pf.checks.find((c) => c.id === "ocr_runtime")?.ok).toBe(false);
    await expect(bridge.activate_subscription("test-key")).resolves.toMatchObject({ ok: false });
  });

  it("start failure remains observable as FAILED instead of silently returning idle", async () => {
    const bridge = createMockBridge({ startFailure: "模拟 OCR 启动失败" });
    const result = await bridge.start_run("normal_farm", 0);
    expect(result.ok).toBe(false);
    expect((await bridge.get_snapshot()).run).toMatchObject({ state: "FAILED", phase: "ERROR", terminal_reason: "模拟 OCR 启动失败" });
  });

  it("update_config 往返保留补丁字段", async () => {
    const bridge = createMockBridge();
    const res = await bridge.update_config({ cycle: 3 });
    expect(res.ok).toBe(true);
    expect(res.errors).toEqual([]);
    expect((await bridge.get_snapshot()).settings.cycle).toBe(3);
  });

  it("createMockBridgeConnection 派发 snapshot_changed / run_status_changed / log_appended 信号", async () => {
    const conn = createMockBridgeConnection();
    const onRun = vi.fn();
    const onSnap = vi.fn();
    const onLog = vi.fn();

    conn.signals.run_status_changed.connect(onRun);
    conn.signals.snapshot_changed.connect(onSnap);
    conn.signals.log_appended.connect(onLog);

    await conn.bridge.update_shell({ theme: "dark" });
    expect(onSnap).toHaveBeenCalled();
    const snap = JSON.parse(onSnap.mock.calls[0][0]);
    expect(snap.shell.theme).toBe("dark");

    await conn.bridge.start_run("normal_farm", 0);
    expect(onRun).toHaveBeenCalled();
    const run = JSON.parse(onRun.mock.calls[0][0]);
    expect(run.state).toBe("STARTING");
    expect(run.phase).toBe("BOOT");
    expect(onLog).toHaveBeenCalled();

    await conn.bridge.stop_run();
    const stopCall = onRun.mock.calls.find((call) => {
      const parsed = JSON.parse(call[0]);
      return parsed.state === "STOPPING";
    });
    expect(stopCall).toBeDefined();
  });
});
