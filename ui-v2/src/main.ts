// Task 2：仅建立桥接选择入口。OD12 产品逻辑仍内联在 index.html。
// Task 5 在此接线 qtBridge（get_snapshot 初始化 state、信号订阅、按钮替换点）。
import type { DashboardBridge } from "./bridge/types";

let bridge: DashboardBridge | null = null;

if (import.meta.env.MODE !== "production") {
  // dev/浏览器测试：诚实 mock，形状与 types.ts 一致。
  void import("./bridge/mockBridge").then(({ createMockBridge }) => {
    bridge = createMockBridge();
  });
}
// production（QWebEngine file://）：qtBridge 于 Task 5 接入；在此之前保持 null，
// 页面行为与 OD12 静态壳一致，不做任何静默降级。

export function getBridge(): DashboardBridge | null {
  return bridge;
}
