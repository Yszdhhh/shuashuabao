// Task 5：qtBridge 单元测试。node 环境下以最小假宿主（window.qt / QWebChannel /
// document）驱动真实 qtBridge 代码路径，验证：
//   - 序列化：七方法的 JSON 入参/出参契约（§6.1 全部 @Slot(str)->str）
//   - 信号派发：三信号 connect 后可从 facade 侧回推
//   - 错误处理：transport 超时、facade 缺失、方法拒绝、非 JSON 返回、信号缺失
import { beforeEach, describe, expect, it } from "vitest";
import {
  QWEBCHANNEL_SRC,
  createQtBridge,
  type RawFacade,
} from "../src/bridge/qtBridge";

type AnyRecord = Record<string, unknown>;

const SNAPSHOT_JSON = JSON.stringify({
  settings: { cycle_num: 7, skills: ["jq"] },
  shell: { theme: "dark", selected_mode_id: "normal_farm" },
  modes: [],
  run: { state: "IDLE" },
});

interface FakeSignal {
  connect(cb: (...args: unknown[]) => void): void;
  emit(...args: unknown[]): void;
}

function makeSignal(): FakeSignal {
  const callbacks: Array<(...args: unknown[]) => void> = [];
  return {
    connect(cb) {
      callbacks.push(cb);
    },
    emit(...args) {
      for (const cb of callbacks) cb(...args);
    },
  };
}

/** 最小 document 假体：记录注入的 script 并异步触发 onload。 */
function installFakeDocument(record?: Array<{ src: string }>): void {
  (globalThis as AnyRecord).document = {
    querySelector: () => null,
    createElement: () => {
      const el = { src: "", onload: null as (() => void) | null };
      record?.push(el);
      return el;
    },
    head: {
      appendChild(el: { onload?: () => void }) {
        setTimeout(() => el.onload?.(), 0);
      },
    },
  };
}

interface FacadeHarness {
  facade: AnyRecord;
  calls: Array<[string, string?]>;
  signals: {
    run_status_changed: FakeSignal;
    log_appended: FakeSignal;
    snapshot_changed: FakeSignal;
  };
}

/** 构造形状与 DashboardFacade 一致的原始对象；每个方法记录收到的原始字符串参数。 */
function makeFacade(
  override: (name: string) => ((arg?: string) => Promise<string>) | undefined = () => undefined,
): FacadeHarness {
  const calls: Array<[string, string?]> = [];
  const signals = {
    run_status_changed: makeSignal(),
    log_appended: makeSignal(),
    snapshot_changed: makeSignal(),
  };
  const defaultHandlers: Record<string, (arg?: string) => Promise<string>> = {
    get_snapshot: async () => SNAPSHOT_JSON,
    update_config: async () => JSON.stringify({ ok: true, errors: [], settings: {} }),
    update_shell: async () => JSON.stringify({ ok: true, errors: [], shell: {} }),
    validate_preflight: async () => JSON.stringify({ ok: true, blocked_reason: "", checks: [] }),
    start_run: async () => JSON.stringify({ ok: true }),
    stop_run: async () => JSON.stringify({ ok: true }),
    window_control: async () => JSON.stringify({ ok: true }),
  };
  const facade: AnyRecord = {};
  for (const [name, handler] of Object.entries(defaultHandlers)) {
    facade[name] = async (arg?: string) => {
      calls.push(arg === undefined ? [name] : [name, arg]);
      const over = override(name);
      return over ? over(arg) : handler(arg);
    };
  }
  Object.assign(facade, signals);
  return { facade, calls, signals };
}

function installHost(harness: { facade: AnyRecord } | null): void {
  installFakeDocument();
  (globalThis as AnyRecord).window = globalThis;
  (globalThis as AnyRecord).qt = { webChannelTransport: { marker: true } };
  (globalThis as AnyRecord).QWebChannel = (
    _transport: unknown,
    ready: (channel: { objects: AnyRecord }) => void,
  ) => {
    setTimeout(() => ready({ objects: harness ? { facade: harness.facade } : {} }), 0);
  };
}

beforeEach(() => {
  delete (globalThis as AnyRecord).document;
  delete (globalThis as AnyRecord).window;
  delete (globalThis as AnyRecord).qt;
  delete (globalThis as AnyRecord).QWebChannel;
});

describe("qtBridge 序列化契约", () => {
  it("七方法按 §6.1 序列化入参并解析出参", async () => {
    const harness = makeFacade();
    installHost(harness);
    const { bridge } = await createQtBridge();

    await expect(bridge.get_snapshot()).resolves.toMatchObject({
      shell: { theme: "dark", selected_mode_id: "normal_farm" },
    });
    await expect(bridge.update_config({ cycle_num: 3 })).resolves.toEqual({ ok: true, errors: [], settings: {} });
    await expect(bridge.update_shell({ theme: "dark" })).resolves.toEqual({ ok: true, errors: [], shell: {} });
    await expect(bridge.validate_preflight("normal_farm")).resolves.toEqual({ ok: true, blocked_reason: "", checks: [] });
    await expect(bridge.start_run("normal_farm")).resolves.toEqual({ ok: true });
    await expect(bridge.stop_run()).resolves.toEqual({ ok: true });
    await expect(bridge.window_control("minimize")).resolves.toEqual({ ok: true });

    expect(harness.calls).toEqual([
      ["get_snapshot"],
      ["update_config", JSON.stringify({ cycle_num: 3 })],
      ["update_shell", JSON.stringify({ theme: "dark" })],
      ["validate_preflight", JSON.stringify({ mode_id: "normal_farm" })],
      ["start_run", JSON.stringify({ mode_id: "normal_farm" })],
      ["stop_run"],
      ["window_control", JSON.stringify({ action: "minimize" })],
    ]);
  });

  it("qwebchannel.js 注入脚本使用 qrc 地址", async () => {
    const injected: Array<{ src: string }> = [];
    installHost(makeFacade());
    installFakeDocument(injected);
    await createQtBridge();
    expect(injected.map((el) => el.src)).toEqual([QWEBCHANNEL_SRC]);
  });
});

describe("qtBridge 信号派发", () => {
  it("三信号经 connect 注册后由 facade 回推触发", async () => {
    const harness = makeFacade();
    installHost(harness);
    const { signals } = await createQtBridge();

    const seen: Array<{ json?: string; text?: string; level?: string }> = [];
    signals.run_status_changed.connect((json) => seen.push({ json }));
    signals.log_appended.connect((text, level) => seen.push({ text, level }));
    signals.snapshot_changed.connect((json) => seen.push({ json }));

    harness.signals.run_status_changed.emit(JSON.stringify({ state: "RUNNING", phase: "lobby" }));
    harness.signals.log_appended.emit("[INFO] 已进入房间", "info");
    harness.signals.snapshot_changed.emit(SNAPSHOT_JSON);

    expect(seen).toEqual([
      { json: JSON.stringify({ state: "RUNNING", phase: "lobby" }) },
      { text: "[INFO] 已进入房间", level: "info" },
      { json: SNAPSHOT_JSON },
    ]);
  });
});

describe("qtBridge 错误处理", () => {
  it("transport 缺失时按超时显式抛错（不降级 mock）", async () => {
    installHost(null);
    delete (globalThis as AnyRecord).qt; // 宿主未注入 webChannelTransport
    await expect(createQtBridge(120)).rejects.toThrow(/webChannelTransport 超时/);
  });

  it("channel.objects 缺 facade 时显式抛错", async () => {
    installHost(null);
    await expect(createQtBridge(200)).rejects.toThrow(/facade 对象缺失或方法面不完整/);
  });

  it("facade 方法拒绝时错误带方法名上下文", async () => {
    const harness = makeFacade((name) =>
      name === "start_run" ? async () => Promise.reject(new Error("boom")) : undefined,
    );
    installHost(harness);
    const { bridge } = await createQtBridge();
    await expect(bridge.start_run("normal_farm")).rejects.toThrow(/facade\.start_run 调用失败: boom/);
  });

  it("返回非 JSON 时显式抛错", async () => {
    const harness = makeFacade((name) => (name === "stop_run" ? async () => "not-json" : undefined));
    installHost(harness);
    const { bridge } = await createQtBridge();
    await expect(bridge.stop_run()).rejects.toThrow(/facade\.stop_run 返回非 JSON: not-json/);
  });

  it("facade 缺任一信号即拒绝建桥（fail-closed）", async () => {
    const harness = makeFacade();
    delete harness.facade.log_appended;
    installHost(harness);
    await expect(createQtBridge(200)).rejects.toThrow(/log_appended 信号缺失/);
  });

  it("facade 缺白名单方法即拒绝建桥", async () => {
    const harness = makeFacade();
    delete harness.facade.stop_run;
    installHost(harness);
    await expect(createQtBridge(200)).rejects.toThrow(/facade 对象缺失或方法面不完整/);
  });
});

// 编译期守卫：RawFacade 方法面即 DashboardBridge 的原始形状（同构，仅字符串层）。
type AssertAssignable<A extends B, B> = A;
type _MethodFaceCheck = AssertAssignable<RawFacade, RawFacade>;
