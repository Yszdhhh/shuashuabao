// 生产 QWebChannel 桥（设计规格 §6/§7）。注入 qrc:///qtwebchannel/qwebchannel.js，
// 连接 window.qt.webChannelTransport → channel.objects.facade（宿主唯一注册对象）。
// 白名单方法入参出参均为 JSON 字符串：这里统一 stringify / parse。
// 超时、缺 transport、facade 缺方法或缺信号一律显式抛错（main.ts 渲染报错页），
// 不静默降级 mock（§7）。
import type {
  ConfigPatch,
  ConfigPatchResult,
  DashboardBridge,
  DashboardBridgeSignals,
  BridgeInfoDTO,
  PreflightDTO,
  RpcResponse,
  RunResult,
  ShellPatchResult,
  SnapshotDTO,
  WindowLayout,
} from "./types";
export const QWEBCHANNEL_SRC = "qrc:///qtwebchannel/qwebchannel.js";
export const FACADE_OBJECT_NAME = "facade";
export const BRIDGE_SCHEMA_VERSION = 2;

/** QWebChannel 连接/transport 等待的默认超时（ms）。 */
export const DEFAULT_TIMEOUT_MS = 5000;

type SignalLike<T extends unknown[]> = { connect(cb: (...args: T) => void): void };

/** Versioned Slot surface: subscription and the handshake are mandatory. */
const WHITELIST_METHODS = [
  "get_bridge_info",
  "get_snapshot",
  "update_config",
  "update_shell",
  "validate_preflight",
  "start_run",
  "stop_run",
  "window_control",
  "set_window_layout",
  "activate_subscription",
] as const;

/** QWebChannel 注入脚本后暴露在 window 上的原始 facade 形状。 */
export type RawFacade = {
  get_bridge_info(): Promise<string>;
  get_snapshot(): Promise<string>;
  update_config(patch_json: string): Promise<string>;
  update_shell(patch_json: string): Promise<string>;
  validate_preflight(mode_id_json: string): Promise<string>;
  start_run(mode_id_json: string): Promise<string>;
  stop_run(): Promise<string>;
  window_control(action_json: string): Promise<string>;
  set_window_layout(layout_json: string): Promise<string>;
  activate_subscription(key_json: string): Promise<string>;
} & {
  snapshot_changed?: SignalLike<[string]>;
  run_status_changed?: SignalLike<[string]>;
  log_appended?: SignalLike<[string, string]>;
};

declare global {
  interface Window {
    qt?: { webChannelTransport: unknown };
    QWebChannel?: (
      transport: unknown,
      onReady: (channel: { objects: Record<string, unknown> }) => void,
    ) => void;
  }
}

function injectScript(src: string): Promise<void> {
  if (document.querySelector(`script[src="${src}"]`)) return Promise.resolve();
  return new Promise<void>((resolve, reject) => {
    const el = document.createElement("script");
    el.src = src;
    el.onload = () => resolve();
    el.onerror = () => reject(new Error(`无法加载 ${src}（Qt WebChannel 注入脚本缺失）`));
    document.head.appendChild(el);
  });
}

async function waitForTransport(timeoutMs: number): Promise<unknown> {
  const deadline = Date.now() + timeoutMs;
  while (!(window.qt && window.qt.webChannelTransport)) {
    if (Date.now() >= deadline) {
      throw new Error(`等待 qt.webChannelTransport 超时（${timeoutMs}ms）：页面不在 QWebEngine 宿主中`);
    }
    await new Promise((r) => setTimeout(r, 50));
  }
  return window.qt.webChannelTransport;
}

function openFacade(transport: unknown): Promise<RawFacade> {
  return new Promise<RawFacade>((resolve, reject) => {
    if (typeof window.QWebChannel !== "function") {
      reject(new Error("QWebChannel 全局缺失：qwebchannel.js 未正确注入"));
      return;
    }
    try {
      window.QWebChannel(transport, (channel) => {
        resolve(channel.objects[FACADE_OBJECT_NAME] as RawFacade);
      });
    } catch (err) {
      reject(new Error(`QWebChannel 建立失败: ${String(err)}`));
    }
  });
}

async function withTimeout<T>(p: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  let timer: any;
  const timeoutPromise = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(message)), timeoutMs);
  });
  try {
    return await Promise.race([p, timeoutPromise]);
  } finally {
    clearTimeout(timer);
  }
}

export const DEFAULT_CALL_TIMEOUT_MS = 10_000;
/** Frozen preflight may wait on a first-time manifest verify (~20s) plus staging permit. */
export const PREFLIGHT_CALL_TIMEOUT_MS = 60_000;

async function callMethod<T>(name: string, pending: Promise<string>, timeoutMs = DEFAULT_CALL_TIMEOUT_MS): Promise<T> {
  let raw: string;
  try {
    raw = await withTimeout(pending, timeoutMs, `facade.${name} 调用超时（>${timeoutMs}ms）`);
  } catch (err) {
    throw new Error(`facade.${name} 调用失败: ${err instanceof Error ? err.message : String(err)}`);
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new Error(`facade.${name} 返回非 JSON: ${raw.slice(0, 80)}`);
  }
}

// 白名单方法统一 JSON 序列化出口；mode_id/action/layout 按 facade
// _parse_keyed 契约包成单键对象。
function wrapFacade(facade: RawFacade): DashboardBridge {
  return {
    get_bridge_info: () => callMethod<BridgeInfoDTO>("get_bridge_info", facade.get_bridge_info()),
    get_snapshot: () => callMethod<SnapshotDTO>("get_snapshot", facade.get_snapshot()),
    update_config: (patch: ConfigPatch) =>
      callMethod<ConfigPatchResult>("update_config", facade.update_config(JSON.stringify(patch))),
    update_shell: (patch: Partial<{ theme: "light" | "dark"; selected_mode_id: string }>) =>
      callMethod<ShellPatchResult>("update_shell", facade.update_shell(JSON.stringify(patch))),
    validate_preflight: (mode_id: string) =>
      callMethod<PreflightDTO>(
        "validate_preflight",
        facade.validate_preflight(JSON.stringify({ mode_id })),
        PREFLIGHT_CALL_TIMEOUT_MS,
      ),
    start_run: (mode_id: string, expectedRevision?: number) =>
      callMethod<RunResult>("start_run", facade.start_run(JSON.stringify({ mode_id, expected_settings_revision: expectedRevision }))),
    stop_run: () => callMethod<RunResult>("stop_run", facade.stop_run()),
    window_control: (action: "minimize" | "close") =>
      callMethod<RpcResponse>("window_control", facade.window_control(JSON.stringify({ action }))),
    set_window_layout: (layout: WindowLayout) =>
      callMethod<RpcResponse>("set_window_layout", facade.set_window_layout(JSON.stringify({ layout }))),
    activate_subscription: (key: string) =>
      callMethod<{ ok: boolean; message: string; status?: string; expires_at?: string }>(
        "activate_subscription",
        facade.activate_subscription(JSON.stringify({ key })),
      ),
  };
}

/** 三信号 fail-closed 校验：宿主少暴露任何一个都拒绝建桥。 */
function requireSignals(facade: RawFacade): DashboardBridgeSignals {
  const pick = <T extends unknown[]>(name: keyof RawFacade & string): SignalLike<T> => {
    const signal = facade[name] as SignalLike<T> | undefined;
    if (!signal || typeof signal.connect !== "function") {
      throw new Error(`facade.${name} 信号缺失，拒绝建立桥接`);
    }
    return signal;
  };
  return {
    snapshot_changed: pick<[string]>("snapshot_changed"),
    run_status_changed: pick<[string]>("run_status_changed"),
    log_appended: pick<[string, string]>("log_appended"),
  } as DashboardBridgeSignals;
}

export interface QtBridgeConnection {
  bridge: DashboardBridge;
  signals: DashboardBridgeSignals;
}

/** 连接 QWebChannel 并返回类型化桥 + 三信号句柄。任何失败显式抛错。 */
export async function createQtBridge(timeoutMs = DEFAULT_TIMEOUT_MS): Promise<QtBridgeConnection> {
  await injectScript(QWEBCHANNEL_SRC);
  const transport = await waitForTransport(timeoutMs);
  const facade = await withTimeout(
    openFacade(transport),
    timeoutMs,
    `QWebChannel 连接超时（${timeoutMs}ms）`,
  );
  for (const name of WHITELIST_METHODS) {
    if (!facade || typeof facade[name as keyof RawFacade] !== "function") {
      throw new Error(`facade 对象缺失或方法面不完整（缺 ${name}），拒绝建立桥接`);
    }
  }
  const bridge = wrapFacade(facade);
  const info = await bridge.get_bridge_info();
  if (
    !info.ok
    || info.schema_version !== BRIDGE_SCHEMA_VERSION
    || !Array.isArray(info.required_methods)
    || !Array.isArray(info.required_signals)
    || !WHITELIST_METHODS.every((name) => info.required_methods.includes(name))
    || !["snapshot_changed", "run_status_changed", "log_appended"]
      .every((name) => info.required_signals.includes(name))
  ) {
    throw new Error(
      `facade bridge schema 不匹配（期望 ${BRIDGE_SCHEMA_VERSION}，收到 ${String(info.schema_version)}），拒绝建立桥接`,
    );
  }
  return { bridge, signals: requireSignals(facade) };
}
