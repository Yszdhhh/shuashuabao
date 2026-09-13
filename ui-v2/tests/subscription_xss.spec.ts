import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

/**
 * 订阅 pill / 激活弹窗的 XSS 回归。
 *
 * 看板是挂着 QWebChannel facade 的特权页面，订阅 status / expires_at / live_status
 * 部分来自 facade 与订阅服务端。这里在 vm 沙箱里真实执行 index.html 的经典内联脚本，
 * 用一个记录型假 DOM 观察：动态字符串只能以文本节点落地，写进 innerHTML 的只能是静态骨架。
 */

const htmlPath = path.resolve(__dirname, "../index.html");
const html = fs.readFileSync(htmlPath, "utf-8");
const inlineScript = (html.match(/<script(?![^>]*src=)>([\s\S]*?)<\/script>/i) || [])[1] || "";

const PAYLOADS = [
  "<img src=x onerror=alert(1)>",
  "<svg onload=alert(1)>",
  "\"><img src=x onerror=alert(1)>",
  "'><img src=x onerror=alert(1)>",
  "\" onmouseover=\"alert(1)",
  "' onfocus='alert(1)' autofocus='",
];

// 弹窗骨架里允许出现的静态标签；攻击者提供的任何标签都不在这里。
const MODAL_SKELETON_TAGS = new Set(["div", "p", "h2", "i", "label", "input", "button", "small", "span"]);

type FakeNode = Record<string, any>;

function makeLoose(): any {
  const fn = function () {};
  return new Proxy(fn, {
    get(_t, prop) {
      if (prop === Symbol.toPrimitive) return () => "";
      if (prop === "then") return undefined;
      if (prop === "toString" || prop === "valueOf") return () => "";
      if (prop === "querySelectorAll") return () => [];
      if (prop === "dataset" || prop === "style") return {};
      if (prop === "classList") return { add() {}, remove() {}, toggle() {}, contains: () => false };
      return makeLoose();
    },
    set: () => true,
    apply: () => makeLoose(),
  });
}

function makeTextNode(text: unknown): FakeNode {
  return { nodeType: 3, textContent: String(text) };
}

function makeNode(tag: string, id = ""): FakeNode {
  const node: FakeNode = {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    id,
    className: "",
    title: "",
    value: "",
    dataset: {},
    style: {},
    attrs: {} as Record<string, string>,
    children: [] as FakeNode[],
    htmlWrites: [] as string[],
    _html: null as string | null,
    _text: "",
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    setAttribute(k: string, v: unknown) { this.attrs[k] = String(v); },
    getAttribute(k: string) { return this.attrs[k] ?? null; },
    appendChild(c: FakeNode) { this.children.push(c); return c; },
    addEventListener() {},
    removeEventListener() {},
    focus() {},
    blur() {},
    querySelector: () => makeLoose(),
    querySelectorAll: () => [],
    get innerHTML() { return this._html ?? ""; },
    set innerHTML(v: string) {
      this._html = String(v);
      this.htmlWrites.push(String(v));
      this.children = [];
      this._text = "";
    },
    get textContent() {
      return this._text + this.children.map((c: FakeNode) => c.textContent).join("");
    },
    set textContent(v: string) {
      this._text = String(v);
      this.children = [];
      this._html = null;
    },
  };
  return new Proxy(node, {
    get(t, p) { return p in t ? Reflect.get(t, p, t) : makeLoose(); },
    set(t, p, v) { return Reflect.set(t, p, v, t); },
  });
}

function bootDashboard() {
  const byId = new Map<string, FakeNode>();
  const getById = (id: string) => {
    if (!byId.has(id)) byId.set(id, makeNode("div", id));
    return byId.get(id)!;
  };
  const sandbox: Record<string, unknown> = {
    document: {
      getElementById: getById,
      querySelectorAll: () => [],
      querySelector: () => makeLoose(),
      addEventListener: () => {},
      createElement: (tag: string) => makeNode(tag),
      createTextNode: makeTextNode,
      body: makeLoose(),
      documentElement: makeLoose(),
      activeElement: null,
    },
    addEventListener: () => {},
    removeEventListener: () => {},
    console: { log: () => {}, error: () => {}, warn: () => {} },
    setTimeout: () => 0,
    setInterval: () => 0,
    clearInterval: () => {},
    clearTimeout: () => {},
    requestAnimationFrame: () => 0,
    cancelAnimationFrame: () => {},
    localStorage: { getItem: () => null, setItem: () => {} },
    matchMedia: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }),
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);
  vm.runInContext(inlineScript, context);
  return {
    el: getById,
    run: (code: string) => vm.runInContext(code, context),
    applySubscription: (sub: unknown) => {
      context.__sub = sub;
      vm.runInContext("applySubscription(__sub)", context);
    },
  };
}

function tagsIn(markup: string): string[] {
  return Array.from(markup.matchAll(/<\s*([a-zA-Z][\w-]*)/g), (m) => m[1].toLowerCase());
}

function hasEventAttr(markup: string): boolean {
  return /\son[a-z]+\s*=/i.test(markup);
}

describe("subscription pill / modal render backend strings as text only", () => {
  it("inline script evaluates in the sandbox", () => {
    expect(inlineScript.length).toBeGreaterThan(1000);
    expect(() => bootDashboard()).not.toThrow();
  });

  it("source no longer feeds subscription text into innerHTML", () => {
    expect(html).not.toMatch(/pill\.innerHTML\s*=/);
    expect(html).not.toMatch(/modalSheet"\)\.innerHTML\s*=\s*`[^`]*\$\{nowText\}/);
  });

  for (const payload of PAYLOADS) {
    it(`pill keeps active-state payload as text: ${payload}`, () => {
      const dash = bootDashboard();
      dash.applySubscription({
        active: true,
        status: payload,
        expires_at: payload,
        live_status: payload,
        live_authorized: false,
      });
      const pill = dash.el("subscriptionPill");
      // innerHTML 从未被写入动态字符串；子节点只有静态 dot + 文本节点。
      expect(pill.htmlWrites.join("")).toBe("");
      const elementChildren = pill.children.filter((c: FakeNode) => c.nodeType === 1);
      expect(elementChildren.map((c: FakeNode) => c.tagName)).toEqual(["SPAN"]);
      expect(elementChildren[0].className).toBe("dot");
      expect(Object.keys(elementChildren[0].attrs)).toEqual(["aria-hidden"]);
      const textChildren = pill.children.filter((c: FakeNode) => c.nodeType === 3);
      expect(textChildren).toHaveLength(1);
      expect(textChildren[0].textContent).toContain(payload);
      expect(textChildren[0].textContent).toContain(payload.slice(0, 10));
    });

    it(`pill keeps inactive-state payload as text: ${payload}`, () => {
      const dash = bootDashboard();
      dash.applySubscription({ active: false, status: payload, expires_at: "", live_status: payload });
      const pill = dash.el("subscriptionPill");
      expect(pill.htmlWrites.join("")).toBe("");
      expect(pill.children.filter((c: FakeNode) => c.nodeType === 1)).toHaveLength(1);
      expect(pill.textContent).toBe(payload);
    });

    it(`modal renders only the static skeleton and puts payload in a text node: ${payload}`, () => {
      const dash = bootDashboard();
      dash.applySubscription({
        active: true,
        status: "正常",
        expires_at: payload,
        live_status: payload,
        live_authorized: false,
      });
      dash.run("openSubscriptionModal()");
      const sheet = dash.el("modalSheet");
      const markup = sheet.htmlWrites.join("");
      expect(markup).toContain('id="subscriptionNow"');
      for (const tag of tagsIn(markup)) expect(MODAL_SKELETON_TAGS.has(tag)).toBe(true);
      expect(tagsIn(markup)).not.toContain("img");
      expect(tagsIn(markup)).not.toContain("svg");
      expect(hasEventAttr(markup)).toBe(false);
      expect(markup).not.toContain("alert(1)");
      const nowEl = dash.el("subscriptionNow");
      const text = nowEl.children.filter((c: FakeNode) => c.nodeType === 3).map((c: FakeNode) => c.textContent).join("");
      expect(text).toContain(payload);
      expect(nowEl.children.filter((c: FakeNode) => c.nodeType === 1)).toHaveLength(0);
    });
  }

  it("normal Chinese status, date and LIVE text still display", () => {
    const dash = bootDashboard();
    dash.applySubscription({
      active: true,
      status: "正常",
      expires_at: "2026-12-31T00:00:00Z",
      live_status: "LIVE 已授权",
      live_authorized: true,
    });
    const pill = dash.el("subscriptionPill");
    expect(pill.textContent).toBe("卡密有效 · 2026-12-31 到期 · LIVE 已授权");
    expect(pill.dataset.state).toBe("ok");
    expect(pill.attrs["aria-label"]).toBe("订阅卡密有效 · 2026-12-31 到期 · LIVE 已授权");

    dash.run("openSubscriptionModal()");
    expect(dash.el("subscriptionNow").textContent).toBe("卡密有效 · 2026-12-31 到期 · LIVE 已授权");
    expect(dash.el("modalSheet").innerHTML).toContain("更换并保存");
  });

  it("inactive and expired states keep their fixed Chinese copy", () => {
    const dash = bootDashboard();
    dash.applySubscription({ active: false, status: "未激活" });
    expect(dash.el("subscriptionPill").textContent).toBe("未激活");
    dash.run("openSubscriptionModal()");
    expect(dash.el("subscriptionNow").textContent).toBe("订阅未激活");

    const expired = bootDashboard();
    expired.applySubscription({ active: false, status: "已过期" });
    expired.run("openSubscriptionModal()");
    expect(expired.el("subscriptionNow").textContent).toBe("订阅已过期");
    expect(expired.el("modalSheet").innerHTML).toContain("激活并保存");
  });
});
