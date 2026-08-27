import type { SettingsDTO, StrategyDTO, ConfigPatch, ConfigResult, BridgeAPI } from "./bridge/types";

export let currentSettingsRevision: number = 0;
export function setSettingsRevision(rev: number): void {
  currentSettingsRevision = rev;
}

function generateUUID(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "req-" + Math.random().toString(36).substring(2, 11) + "-" + Date.now();
}

type QueueItem = {
  patch: Partial<SettingsDTO> & { strategy?: Partial<StrategyDTO> };
  resolve: (res: ConfigResult) => void;
  reject: (err: unknown) => void;
};

const queue: QueueItem[] = [];
let processing = false;

export function enqueueConfigPatch(
  patch: Partial<SettingsDTO> & { strategy?: Partial<StrategyDTO> },
  bridge: BridgeAPI
): Promise<ConfigResult> {
  return new Promise((resolve, reject) => {
    queue.push({ patch, resolve, reject });
    processQueue(bridge);
  });
}

async function processQueue(bridge: BridgeAPI): Promise<void> {
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
      if (res.ok && res.settings_revision !== undefined) {
        currentSettingsRevision = res.settings_revision;
      }
      item.resolve(res);
    } catch (err) {
      item.reject(err);
    }
  }

  processing = false;
}

export async function flushConfigQueue(): Promise<void> {
  while (processing || queue.length > 0) {
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}
