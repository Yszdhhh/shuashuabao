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

    const callOrder: string[] = [];
    const mockBridge: Partial<DashboardBridge> = {
      update_config: vi.fn(async (patch: ConfigPatch): Promise<ConfigPatchResult> => {
        callOrder.push(JSON.stringify(patch));
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
    expect(callOrder.length).toBe(2);
  });

  it("ConfigQueue failure -> BROKEN -> resync -> replay -> ACK recovery test", async () => {
    resetStickyFailure();
    setSettingsRevision(5);

    let attempts = 0;
    const mockBridge: Partial<DashboardBridge> = {
      update_config: vi.fn(async (patch: ConfigPatch): Promise<ConfigPatchResult> => {
        attempts++;
        if (attempts === 1) {
          throw new Error("RPC timeout");
        }
        return {
          ok: true,
          request_id: patch.request_id,
          settings_revision: 6,
          snapshot_seq: 10,
          errors: [],
          settings: {},
          strategy: {},
        };
      }),
    };

    // 第一次提交：触发 RPC timeout
    const p1 = enqueueConfigPatch({ strategy: { merchant: { enabled: true, max_rerolls: 3, gold_reserve: 100 } } }, mockBridge as DashboardBridge);
    await expect(p1).rejects.toThrow("RPC timeout");
    expect(getQueueState()).toBe("BROKEN");
    await expect(flushConfigQueue()).rejects.toThrow("RPC timeout");

    // 此时队列处于 BROKEN，新 patch 应被直接拒收
    const pNew = enqueueConfigPatch({ cycle_num: 1 }, mockBridge as DashboardBridge);
    await expect(pNew).rejects.toThrow("BROKEN");

    // 权威 Snapshot 介入重对齐并重放 failed patch
    const snap: SnapshotDTO = {
      request_id: null,
      settings_revision: 5,
      snapshot_seq: 10,
      settings: {},
      strategy: {},
      shell: {} as any,
      modes: [],
      run: {} as any,
    };

    const recoveryRes = await reconcileAndRetry(snap, mockBridge as DashboardBridge);
    expect(recoveryRes?.ok).toBe(true);
    expect(recoveryRes?.settings_revision).toBe(6);
    expect(getQueueState()).toBe("HEALTHY");
    expect(getStickyFailure()).toBeNull();

    // 恢复健康后 flushConfigQueue 应该顺利 pass
    await expect(flushConfigQueue()).resolves.toBeUndefined();
  });

  it("明确 backend reject 时禁止假装成功并保持 BROKEN", async () => {
    resetStickyFailure();
    setSettingsRevision(1);

    const mockBridge: Partial<DashboardBridge> = {
      update_config: vi.fn(async (_patch: ConfigPatch): Promise<ConfigPatchResult> => {
        return {
          ok: false,
          request_id: "req-err",
          settings_revision: 1,
          snapshot_seq: 1,
          errors: ["strategy 与顶层字段重复"],
          settings: {},
          strategy: {},
        };
      }),
    };

    const p = enqueueConfigPatch({ skills: ["a"] }, mockBridge as DashboardBridge);
    await expect(p).rejects.toThrow("strategy 与顶层字段重复");
    expect(getQueueState()).toBe("BROKEN");

    // Snapshot 对齐但重试仍被拒绝
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
