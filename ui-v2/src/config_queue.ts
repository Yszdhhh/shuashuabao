import type { SettingsDTO, StrategyDTO, ConfigPatch, ConfigPatchResult, DashboardBridge } from "./bridge/types";

export let currentSettingsRevision: number = 0;
export function setSettingsRevision(rev: number): void {
  currentSettingsRevision = rev;
}

let stickyFailure: Error | null = null;
export function getStickyFailure(): Error | null {
  return stickyFailure;
}
export function resetStickyFailure(): void {
  stickyFailure = null;
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
    queue.push({ patch, resolve, reject });
    processQueue(bridge);
  });
}

async function processQueue(bridge: DashboardBridge): Promise<void> {
  if (processing || queue.length === 0) return;
  processing = true;

  while (queue.length > 0) {
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
      item.reject(errorObj);
    }
  }

  processing = false;
}

export async function flushConfigQueue(): Promise<void> {
  while (processing || queue.length > 0) {
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  if (stickyFailure !== null) {
    throw stickyFailure;
  }
}
