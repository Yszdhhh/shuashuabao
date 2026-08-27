import type { SettingsDTO, StrategyDTO, ConfigPatch, ConfigPatchResult, DashboardBridge, SnapshotDTO } from "./bridge/types";

export let currentSettingsRevision: number = 0;
export function setSettingsRevision(rev: number): void {
  currentSettingsRevision = rev;
}

export type QueueState = "HEALTHY" | "BROKEN";
let queueState: QueueState = "HEALTHY";
let stickyFailure: Error | null = null;
let failedPatch: (Partial<SettingsDTO> & { strategy?: Partial<StrategyDTO> }) | null = null;

export function getQueueState(): QueueState {
  return queueState;
}

export function getStickyFailure(): Error | null {
  return stickyFailure;
}

export function resetStickyFailure(): void {
  stickyFailure = null;
  failedPatch = null;
  queueState = "HEALTHY";
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

export function enqueueConfigPatch(
  patch: Partial<SettingsDTO> & { strategy?: Partial<StrategyDTO> },
  bridge: DashboardBridge
): Promise<ConfigPatchResult> {
  return new Promise((resolve, reject) => {
    if (queueState === "BROKEN") {
      const err = new Error("配置队列处于 BROKEN 状态，拒绝接收新 patch 直至权威 Snapshot 重新对齐");
      stickyFailure = stickyFailure ?? err;
      reject(err);
      return;
    }
    queue.push({ patch, resolve, reject });
    processQueue(bridge);
  });
}

async function processQueue(bridge: DashboardBridge): Promise<void> {
  if (processing || queue.length === 0) return;
  processing = true;

  while (queue.length > 0) {
    if (queueState === "BROKEN") {
      const err = new Error("配置队列处于 BROKEN 状态，等待同步");
      const item = queue.shift()!;
      item.reject(err);
      continue;
    }

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
      } else {
        if (res.settings_revision !== undefined) {
          currentSettingsRevision = res.settings_revision;
        }
        item.resolve(res);
      }
    } catch (err) {
      const errorObj = err instanceof Error ? err : new Error(String(err));
      stickyFailure = errorObj;
      queueState = "BROKEN";
      failedPatch = item.patch;
      item.reject(errorObj);
    }
  }

  processing = false;
}

export async function reconcileAndRetry(
  snap: SnapshotDTO,
  bridge: DashboardBridge
): Promise<ConfigPatchResult | null> {
  if (snap.settings_revision !== undefined) {
    currentSettingsRevision = snap.settings_revision;
  }
  
  if (queueState !== "BROKEN" || !failedPatch) {
    queueState = "HEALTHY";
    stickyFailure = null;
    failedPatch = null;
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
    return res;
  } catch (err) {
    const errorObj = err instanceof Error ? err : new Error(String(err));
    stickyFailure = errorObj;
    queueState = "BROKEN";
    throw errorObj;
  }
}

export async function flushConfigQueue(): Promise<void> {
  while (processing || queue.length > 0) {
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  if (stickyFailure !== null) {
    throw stickyFailure;
  }
}
