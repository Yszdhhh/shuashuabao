import type { SettingsDTO, StrategyDTO, ConfigPatch, ConfigPatchResult, DashboardBridge, SnapshotDTO } from "./bridge/types";

export let currentSettingsRevision: number = 0;
export function setSettingsRevision(rev: number): void {
  currentSettingsRevision = rev;
}

export type QueueState = "HEALTHY" | "BROKEN";
let queueState: QueueState = "HEALTHY";
let stickyFailure: Error | null = null;
let failedPatch: (Partial<SettingsDTO> & { strategy?: Partial<StrategyDTO> }) | null = null;
let recoveryInFlight: Promise<ConfigPatchResult | null> | null = null;

export function getQueueState(): QueueState {
  return queueState;
}

export function getStickyFailure(): Error | null {
  return stickyFailure;
}

/**
 * Explicit hard reset. Production snapshot handling must not use this to recover a BROKEN queue,
 * because doing so would discard the failed user intent. Recovery must go through
 * reconcileAndRetry()/recoverFromAuthoritativeSnapshot().
 */
export function resetStickyFailure(): void {
  stickyFailure = null;
  failedPatch = null;
  queueState = "HEALTHY";
  recoveryInFlight = null;
}

function generateUUID(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "req-" + Math.random().toString(36).substring(2, 11) + "-" + Date.now();
}

type QueueItem = {
  patch: Partial<SettingsDTO> & { strategy?: Partial<StrategyDTO> };
  resolve: (res: ConfigPatchResult) => void;
  reject: (err: unknown) => void;
};

const queue: QueueItem[] = [];
let processing = false;
let lastBridge: DashboardBridge | null = null;

export function enqueueConfigPatch(
  patch: Partial<SettingsDTO> & { strategy?: Partial<StrategyDTO> },
  bridge: DashboardBridge
): Promise<ConfigPatchResult> {
  lastBridge = bridge;
  return new Promise((resolve, reject) => {
    if (queueState === "BROKEN") {
      const err = new Error("配置队列处于 BROKEN 状态，拒绝接收新 patch 直至权威 Snapshot 重新对齐");
      stickyFailure = stickyFailure ?? err;
      reject(err);
      return;
    }
    queue.push({ patch, resolve, reject });
    void processQueue(bridge);
  });
}

async function processQueue(bridge: DashboardBridge): Promise<void> {
  if (processing || queue.length === 0 || queueState === "BROKEN") return;
  processing = true;

  try {
    while (queue.length > 0 && queueState === "HEALTHY") {
      const item = queue.shift()!;
      const fullPatch: ConfigPatch = {
        ...item.patch,
        request_id: generateUUID(),
        settings_revision: currentSettingsRevision,
      };

      try {
        const res = await bridge.update_config(fullPatch);
        if (!res.ok) {
          const err = new Error(res.errors && res.errors.length > 0 ? res.errors.join("; ") : "配置更新失败");
          stickyFailure = err;
          queueState = "BROKEN";
          failedPatch = item.patch;
          item.reject(err);
          break;
        }
        if (res.settings_revision !== undefined) {
          currentSettingsRevision = res.settings_revision;
        }
        item.resolve(res);
      } catch (err) {
        const errorObj = err instanceof Error ? err : new Error(String(err));
        stickyFailure = errorObj;
        queueState = "BROKEN";
        failedPatch = item.patch;
        item.reject(errorObj);
        break;
      }
    }
  } finally {
    processing = false;
  }
}

export async function reconcileAndRetry(
  snap: SnapshotDTO,
  bridge: DashboardBridge
): Promise<ConfigPatchResult | null> {
  lastBridge = bridge;
  if (snap.settings_revision !== undefined) {
    currentSettingsRevision = snap.settings_revision;
  }

  if (queueState !== "BROKEN" || !failedPatch) {
    return null;
  }

  const patchToRetry = failedPatch;
  const fullPatch: ConfigPatch = {
    ...patchToRetry,
    request_id: generateUUID(),
    settings_revision: currentSettingsRevision,
  };

  try {
    const res = await bridge.update_config(fullPatch);
    if (!res.ok) {
      const err = new Error(res.errors && res.errors.length > 0 ? res.errors.join("; ") : "重试配置更新仍被拒绝");
      stickyFailure = err;
      queueState = "BROKEN";
      throw err;
    }
    if (res.settings_revision !== undefined) {
      currentSettingsRevision = res.settings_revision;
    }
    queueState = "HEALTHY";
    stickyFailure = null;
    failedPatch = null;

    // The first failed intent is now durably ACKed. Resume any later intents that were already
    // queued before the failure; they were intentionally preserved instead of shift/reject loss.
    await processQueue(bridge);
    return res;
  } catch (err) {
    const errorObj = err instanceof Error ? err : new Error(String(err));
    stickyFailure = errorObj;
    queueState = "BROKEN";
    throw errorObj;
  }
}

/**
 * Production recovery entry point for an authoritative snapshot. It serializes concurrent
 * snapshot signals so the same failed patch cannot be replayed twice.
 */
export async function recoverFromAuthoritativeSnapshot(
  snap: SnapshotDTO,
  bridge?: DashboardBridge | null,
): Promise<ConfigPatchResult | null> {
  const activeBridge = bridge ?? lastBridge;
  if (snap.settings_revision !== undefined) {
    currentSettingsRevision = snap.settings_revision;
  }
  if (queueState !== "BROKEN" || !failedPatch) return null;
  if (!activeBridge) {
    const err = new Error("配置队列需要恢复，但当前 Bridge 不可用");
    stickyFailure = err;
    queueState = "BROKEN";
    throw err;
  }
  if (!recoveryInFlight) {
    recoveryInFlight = reconcileAndRetry(snap, activeBridge).finally(() => {
      recoveryInFlight = null;
    });
  }
  return recoveryInFlight;
}

export async function flushConfigQueue(): Promise<void> {
  while (processing || recoveryInFlight !== null || (queue.length > 0 && queueState === "HEALTHY")) {
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  if (stickyFailure !== null) {
    throw stickyFailure;
  }
}
