import { describe, it, expect, beforeEach } from "vitest";
import {
  enqueueConfigPatch,
  flushConfigQueue,
  resetStickyFailure,
  setSettingsRevision,
  currentSettingsRevision,
  getStickyFailure,
} from "../src/config_queue";
import type { DashboardBridge, ConfigPatch, ConfigPatchResult } from "../src/bridge/types";

describe("config_queue", () => {
  beforeEach(() => {
    resetStickyFailure();
    setSettingsRevision(0);
  });

  it("processes successful patches in FIFO order with UUID request_id", async () => {
    const executed: ConfigPatch[] = [];
    const mockBridge: Partial<DashboardBridge> = {
      update_config: async (patch: ConfigPatch): Promise<ConfigPatchResult> => {
        executed.push(patch);
        return {
          ok: true,
          request_id: patch.request_id,
          settings_revision: (patch.settings_revision ?? 0) + 1,
          snapshot_seq: 1,
        };
      },
    };

    const p1 = enqueueConfigPatch({ cycle_num: 5 }, mockBridge as DashboardBridge);
    const p2 = enqueueConfigPatch(
      {
        strategy: {
          bonds: ["祝福", "成长"],
          attributes: ["int"],
        },
      },
      mockBridge as DashboardBridge
    );

    const [r1, r2] = await Promise.all([p1, p2]);
    expect(r1.ok).toBe(true);
    expect(r2.ok).toBe(true);
    expect(executed.length).toBe(2);
    expect(executed[0].request_id).toMatch(/^[0-9a-f-]+|req-/);
    expect(executed[1].settings_revision).toBe(1);
    expect(currentSettingsRevision).toBe(2);
  });

  it("sets stickyFailure and flushConfigQueue rejects when update_config returns ok=false", async () => {
    const mockBridge: Partial<DashboardBridge> = {
      update_config: async (): Promise<ConfigPatchResult> => {
        return {
          ok: false,
          request_id: "test",
          settings_revision: 0,
          snapshot_seq: 1,
          errors: ["settings_revision 已过期"],
        };
      },
    };

    let caughtError: Error | null = null;
    try {
      await enqueueConfigPatch({ cycle_num: 5 }, mockBridge as DashboardBridge);
    } catch (e) {
      caughtError = e as Error;
    }

    expect(caughtError).not.toBeNull();
    expect(caughtError?.message).toContain("settings_revision 已过期");
    expect(getStickyFailure()).not.toBeNull();

    // flushConfigQueue must reject immediately due to sticky failure
    await expect(flushConfigQueue()).rejects.toThrow("settings_revision 已过期");
  });

  it("sets stickyFailure and flushConfigQueue rejects on RPC network/exception error", async () => {
    const mockBridge: Partial<DashboardBridge> = {
      update_config: async (): Promise<ConfigPatchResult> => {
        throw new Error("Network RPC disconnected");
      },
    };

    let caughtError: Error | null = null;
    try {
      await enqueueConfigPatch({ cycle_num: 5 }, mockBridge as DashboardBridge);
    } catch (e) {
      caughtError = e as Error;
    }

    expect(caughtError).not.toBeNull();
    expect(caughtError?.message).toBe("Network RPC disconnected");
    expect(getStickyFailure()?.message).toBe("Network RPC disconnected");

    await expect(flushConfigQueue()).rejects.toThrow("Network RPC disconnected");
  });
});
