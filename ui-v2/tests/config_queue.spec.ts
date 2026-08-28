import { describe, expect, it, vi } from "vitest";
import {
  enqueueConfigPatch,
  flushConfigQueue,
  setSettingsRevision,
  getStickyFailure,
  resetStickyFailure,
  reconcileAndRetry,
  getQueueState,
} from "../src/config_queue";
import type { DashboardBridge, ConfigPatch, ConfigPatchResult, SnapshotDTO } from "../src/bridge/types";

describe("ConfigQueue 串行化与 Recovery 测试", () => {
  it("按 FIFO 顺序执行并在成功时更新 revision", async () => {
    resetStickyFailure();
    setSettingsRevision(10);

    const callOrder: ConfigPatch[] = [];
    const mockBridge: Partial<DashboardBridge> = {
      update_config: vi.fn(async (patch: ConfigPatch): Promise<ConfigPatchResult> => {
        callOrder.push(patch);
        return {
          ok: true,
          request_id: patch.request_id,
          settings_revision: patch.settings_revision + 1,
          snapshot_seq: 1,
          errors: [],
          settings: {},
          strategy: {},
        };
      }),
    };

    const p1 = enqueueConfigPatch({ cycle_num: 5 }, mockBridge as DashboardBridge);
    const p2 = enqueueConfigPatch({ cycle_num: 10 }, mockBridge as DashboardBridge);

    const [res1, res2] = await Promise.all([p1, p2]);
    expect(res1.settings_revision).toBe(11);
    expect(res2.settings_revision).toBe(12);
    expect(callOrder.map((p) => p.cycle_num)).toEqual([5, 10]);
    expect(callOrder[1].settings_revision).toBe(11);
  });

  it("production snapshot hook replays failed intent then preserves remaining FIFO intents", async () => {
    resetStickyFailure();
    setSettingsRevision(5);

    const calls: ConfigPatch[] = [];
    let attempts = 0;
    const mockBridge: Partial<DashboardBridge> = {
      update_config: vi.fn(async (patch: ConfigPatch): Promise<ConfigPatchResult> => {
        calls.push(patch);
        attempts += 1;
        if (attempts === 1) {
          throw new Error("RPC timeout");
        }
        return {
          ok: true,
          request_id: patch.request_id,
          settings_revision: patch.settings_revision + 1,
          snapshot_seq: 10 + attempts,
          errors: [],
          settings: {},
          strategy: {},
        };
      }),
    };

    // A starts first; B is already queued before A's rejected promise resumes.
    const pA = enqueueConfigPatch({ cycle_num: 1 }, mockBridge as DashboardBridge);
    const pB = enqueueConfigPatch({ cycle_num: 2 }, mockBridge as DashboardBridge);

    await expect(pA).rejects.toThrow("RPC timeout");
    expect(getQueueState()).toBe("BROKEN");
    await expect(flushConfigQueue()).rejects.toThrow("RPC timeout");

    // This is the exact production order in main.ts applySnapshot(): set revision, then reset.
    // setSettingsRevision must trigger replay synchronously; resetStickyFailure must therefore
    // refuse to discard failedPatch while recovery is in flight.
    setSettingsRevision(20);
    resetStickyFailure();

    await expect(flushConfigQueue()).resolves.toBeUndefined();
    const resB = await pB;

    expect(getQueueState()).toBe("HEALTHY");
    expect(getStickyFailure()).toBeNull();
    expect(resB.settings_revision).toBe(22);

    // A failed at rev5; authoritative snapshot resynced to rev20; A replayed at rev20 and ACKed
    // rev21; only then did preserved B run at rev21 and ACK rev22.
    expect(calls.map((p) => p.cycle_num)).toEqual([1, 1, 2]);
    expect(calls.map((p) => p.settings_revision)).toEqual([5, 20, 21]);
  });

  it("明确 backend reject 时禁止假装成功并保持 BROKEN", async () => {
    resetStickyFailure();
    setSettingsRevision(1);

    const mockBridge: Partial<DashboardBridge> = {
      update_config: vi.fn(async (_patch: ConfigPatch): Promise<ConfigPatchResult> => ({
        ok: false,
        request_id: "req-err",
        settings_revision: 1,
        snapshot_seq: 1,
        errors: ["strategy 与顶层字段重复"],
        settings: {},
        strategy: {},
      })),
    };

    const p = enqueueConfigPatch({ skills: ["a"] }, mockBridge as DashboardBridge);
    await expect(p).rejects.toThrow("strategy 与顶层字段重复");
    expect(getQueueState()).toBe("BROKEN");

    // Explicit recovery API remains available for callers with a full authoritative snapshot;
    // an authoritative backend rejection must keep the queue BROKEN.
    const snap: SnapshotDTO = {
      request_id: null,
      settings_revision: 1,
      snapshot_seq: 2,
      settings: {},
      strategy: {},
      shell: {} as any,
      modes: [],
      run: {} as any,
    };
    await expect(reconcileAndRetry(snap, mockBridge as DashboardBridge)).rejects.toThrow("strategy 与顶层字段重复");
    expect(getQueueState()).toBe("BROKEN");
  });
});
