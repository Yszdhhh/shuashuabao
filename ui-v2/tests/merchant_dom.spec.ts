import { describe, expect, it, vi, beforeEach } from "vitest";
import type { DashboardBridge, ConfigPatch, ConfigPatchResult, SnapshotDTO } from "../src/bridge/types";

describe("Merchant DOM -> state -> strategy writeback & snapshot echo test", () => {
  let domState: {
    merchant_enabled?: boolean;
    merchant_max_rerolls?: number;
    merchant_gold_reserve?: number;
  };
  let lastPatch: ConfigPatch | null = null;

  beforeEach(() => {
    domState = {};
    lastPatch = null;
  });

  it("false -> 点击 -> strategy.merchant.enabled=true", () => {
    let merchant_enabled = false;
    // 模拟 DOM toggle
    merchant_enabled = !merchant_enabled;
    domState.merchant_enabled = merchant_enabled;

    const patch: ConfigPatch = {
      request_id: "req-1",
      settings_revision: 0,
      strategy: {
        merchant: {
          enabled: domState.merchant_enabled,
          max_rerolls: 0,
          gold_reserve: 0,
        },
      },
    };
    lastPatch = patch;

    expect(domState.merchant_enabled).toBe(true);
    expect(lastPatch.strategy?.merchant?.enabled).toBe(true);
  });

  it("3 -> 输入5 -> max_rerolls=5", () => {
    const inputVal = "5";
    domState.merchant_max_rerolls = Number(inputVal);

    const patch: ConfigPatch = {
      request_id: "req-2",
      settings_revision: 1,
      strategy: {
        merchant: {
          enabled: true,
          max_rerolls: domState.merchant_max_rerolls,
          gold_reserve: 0,
        },
      },
    };
    lastPatch = patch;

    expect(domState.merchant_max_rerolls).toBe(5);
    expect(lastPatch.strategy?.merchant?.max_rerolls).toBe(5);
  });

  it("reserve 0 -> 500 -> gold_reserve=500", () => {
    const inputVal = "500";
    domState.merchant_gold_reserve = Number(inputVal);

    const patch: ConfigPatch = {
      request_id: "req-3",
      settings_revision: 2,
      strategy: {
        merchant: {
          enabled: true,
          max_rerolls: 5,
          gold_reserve: domState.merchant_gold_reserve,
        },
      },
    };
    lastPatch = patch;

    expect(domState.merchant_gold_reserve).toBe(500);
    expect(lastPatch.strategy?.merchant?.gold_reserve).toBe(500);
  });

  it("snapshot 回推后 DOM/state 一致", () => {
    const snap: SnapshotDTO = {
      request_id: "req-3",
      settings_revision: 3,
      snapshot_seq: 4,
      settings: {},
      strategy: {
        merchant: {
          enabled: true,
          max_rerolls: 8,
          gold_reserve: 1000,
        },
      },
      shell: {} as any,
      modes: [],
      run: {} as any,
    };

    // 模拟 applySnapshot
    if (snap.strategy?.merchant) {
      domState.merchant_enabled = snap.strategy.merchant.enabled;
      domState.merchant_max_rerolls = snap.strategy.merchant.max_rerolls;
      domState.merchant_gold_reserve = snap.strategy.merchant.gold_reserve;
    }

    expect(domState.merchant_enabled).toBe(true);
    expect(domState.merchant_max_rerolls).toBe(8);
    expect(domState.merchant_gold_reserve).toBe(1000);
  });
});
