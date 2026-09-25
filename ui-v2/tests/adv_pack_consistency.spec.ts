import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf-8");
const mainTs = readFileSync(new URL("../src/main.ts", import.meta.url), "utf-8");

function advOptions(): Array<{ id: string; label: string }> {
  const m = html.match(/const ADV = \[(.*?)\];/s);
  if (!m) throw new Error("index.html 里找不到 const ADV");
  return [...m[1].matchAll(/\{id:"([^"]+)",label:"([^"]+)"\}/g)].map((x) => ({ id: x[1], label: x[2] }));
}

function advPackCards(): Record<string, string[]> {
  const m = mainTs.match(/const ADV_PACK_CARDS[^=]*=\s*\{(.*?)\n\};/s);
  if (!m) throw new Error("src/main.ts 里找不到 ADV_PACK_CARDS");
  return Object.fromEntries(
    [...m[1].matchAll(/(\w+):\s*\[([^\]]*)\]/g)].map((x) => [
      x[1],
      [...x[2].matchAll(/"([^"]+)"/g)].map((y) => y[1]),
    ]),
  );
}

describe("haizeiwang advanced pack", () => {
  it("看板选项列表里有海贼王显示名", () => {
    expect(advOptions()).toContainEqual({ id: "haizeiwang", label: "海贼王" });
  });

  it("勾选海贼王后展开的 cards 包含其成员", () => {
    expect(advPackCards()["haizeiwang"]).toEqual(
      ["见习海贼", "四皇", "凯多", "红发", "白胡子", "大妈"],
    );
  });

  it("选项列表与展开表键集合一致（防漂移）", () => {
    expect(new Set(advOptions().map((p) => p.id))).toEqual(new Set(Object.keys(advPackCards())));
  });
});
