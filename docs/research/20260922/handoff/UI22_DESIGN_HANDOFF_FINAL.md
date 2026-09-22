# UI22 设计交接（最终版）

> 用途：主架构拿到参考文件后做差异审查，**把有效增量合进当前源码**。
> 禁止：直接用参考文件覆盖当前源码；热改安装目录 `dist`。
> 「结束脚本」（after-goal / after-room 的 stop 选项）**本版不开放**。

---

## 1. 交付文件与校验值

### 1.1 参考文件（UI-22 最终设计）

| 项 | 值 |
|---|---|
| 文件名 | `UI22_index.reference.html` |
| 长度 | 438,182 字节，6,978 行，全文 LF，无 BOM |
| SHA-256（原始字节） | `5a7824ab275ea313686ecaa40a979f5668d802978286e51192402e7a97ee6f63` |
| Git blob（`git hash-object`） | `0d285578ad537058cbb0a0f283232684892bd867` |
| CRLF 形态的 SHA-256 | `c200b0884c53c55e9e9bd6ba154a2453850d3f8f944ed5b75b79bb782c748cfe`（Windows autocrlf 检出后文件哈希会变成这个；blob 仍是 `0d285578…`） |

### 1.2 基线文件（参考文件就是在这份上改出来的）

| 项 | 值 |
|---|---|
| 文件名 | `UI22_index.baseline-bc228baf.html` |
| 真实来源 | **源码工作区文件**：`G:\刷刷宝\GameScript-Local\ui-v2\index.html`。2026-09-21 写入 UI-22 之前原样读取，文件 mtime 为 2026-09-15 15:01:57 UTC。不是 dist，也不是其它副本。 |
| 长度 | 302,068 字节，4,962 行，全文 CRLF（Windows 检出形态） |
| SHA-256（原始字节，CRLF） | `d29b572c5fd1d8d5a3029c8c0333f17ae8b63f601a4eeaaa1550d36d2e096f2c` |
| 原始字节 blob（不做换行归一，`git hash-object --no-filters`） | `ab335c9def3d6890b51dbbbb5748c648ca43bba3` |
| LF 归一后 SHA-256 | `fe61131f0dd3f5086b48181477e9b1d32714cb08de24cd56b6a817a69d936152`（297,106 字节） |
| LF 归一后 blob（`git hash-object`，autocrlf 生效） | `e974ddffa40945562c697d5ce8d35dda699cf10f` = **`bc228baf:ui-v2/index.html`** |

**解释：** 之前给出的 `ab335c9d…` 是对 CRLF 原始字节算的 blob，没做换行归一。换行归一之后得到 `e974ddff…`，正好就是仓库 `bc228baf:ui-v2/index.html` 的 blob。所以基线**内容**与 bc228baf 源码完全一致，差别只在工作区的 CRLF 换行。

### 1.3 与当前主架构的关系

- 当前 `6a4bba4:ui-v2/index.html` 的 blob 是 `1bbad769baf09d8f37e199659a11ae9b84925b27`，工作区 SHA-256 是 `d7f49253ab9fcfedc19302c8b91231abc29e7e90df184659a8f0d0d91ef67881`。
- 参考文件的 LF、CRLF、BOM、多一个或少一个结尾换行等形态都已逐一核对，哈希**都不等于**上面两个值。
- 结论：6a4bba4 提交的内容与 UI-22 参考文件不同，**不是换行造成的**。请按第 5 节做三方比对（基线 → 参考，基线 → 6a4bba4），保留 6a4bba4 里的有效增量。

---

## 2. 改动范围（基线 → 参考）

参考文件 = 基线 + 以下三类改动。`src/main.ts`、`src/bridge/*`、`src/config_queue.ts`、`tests/*`、`public/*`、宿主 Python **都没有改**。

### A. 恢复一批视觉和交互修复（这些在 6a906709 构建里有，bc228baf 源码里没有）

| 区域 | 内容 |
|---|---|
| 字体 | `--font-display` / `--font-body` / `--p-font` 改为 `"Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans SC", …` 优先 |
| 按钮 | 新增 `--p-btn-capsule: 999px`；`.gold` / `.primary` / `.secondary` / `.ghost-btn.solid` / `.hud-stop` / `.bond-actions` 改用胶囊圆角；新增 `--p-gold-spec` 光泽层 |
| 工具栏分组 | 标题栏新增 `.chrome-tools`（包裹 `#btnTheme`、`#btnWizard`）和 `.win-cluster`（包裹 `#btnMin`、`#btnClose`）；底栏新增 `.footer-tools`（包裹 `#btnSwitchMode` 至 `#btnActivateKey`）。附带整段分组样式、深浅主题、`prefers-reduced-transparency` 与 `prefers-reduced-motion` 降级 |
| 抽屉 | `.drawer` 宽度 `min(320px, 100%)`；恢复 `.drawer .switch-row` 样式 |
| 浮层定位 | 新增 `layoutOverlays()`，统一给 `#drawer` / `#drawerBackdrop` / `#modalLayer` 设置 top/bottom；`setDrawer()` 改为调用它；窗口 resize 时若有抽屉或弹窗打开就重排；`#btnMore` 聚焦前先判断可见 |
| 大小窗切换 | 场景切换改为「`win-swap` 隐藏 → 下一帧 `setScene()` → 失败回滚」（rAF），替代 120ms 定时器淡出；`.win-swap` 改为 `visibility:hidden; pointer-events:none` |
| 切到小窗时 | `setScene()` 先 `closeMenus()`；小窗下自动收起抽屉，以及 `rep` / `subscription` 弹窗；切换后调用 `layoutOverlays()` |
| 蹭车搜房 | 「结束规则」卡片内恢复「搜房」行（`.hitch-search-row`：`#hitchSearchCard` + `#btnHitchAdvanced`），「战后目标」表头里不再重复出现这两个按钮。**ID 不变**，`main.ts` 的 `Ct()` 显隐逻辑照常生效 |
| 其它 | `.hud-stop` 胶囊化；游戏窗口镜像圆角 12px；某标题字重和字距 600 / 0.02em |

**bc228baf 源码新增的龙珠图标（`.dragon-icon-wrap`、`dragonIconSvg()`、龙珠 `<h4>`、`#lblDragon` 前的小图标、启动摘要里的图标）全部保留。**

### B. UI 体验层（纯视图层，新增）

- CSS：追加在 `</style>` 前，以注释 `刷刷宝 UI 体验层` 开头。
- JS：独立的 `<script id="sb-ux-layer">` 块，位于 `<script type="module" src="./src/main.ts"></script>` 之前。
  - 必须保持独立：契约测试只在 Node vm 里执行第一个内联脚本；体验层用到了 `requestAnimationFrame` / `MutationObserver` 等浏览器 API。
- 功能：
  - 启动过场、预检弹层、完成过场、激活仪式；
  - 钛银主色（`html[data-accent]`，默认 titanium）；
  - 方案保存和切换；
  - 宝物设置移到技能搭配右侧，只显示名称，悬停看说明；
  - 羁绊分组显示；
  - 高级设置抽屉里新增「失败 X 局，降低 Y 级关卡难度」；
  - 底部运行日志抽屉；
  - 二级窗口互斥（抽屉、弹窗、日志抽屉同时只开一个）；
  - 按实际窗口尺寸分配宽高的自适应布局；
  - 标题栏构建号 `UI-22`。
- 附带两处 HTML 替换：抽屉标题「宝物设置」→「高级设置」；底栏按钮文字「宝物设置」→「高级设置」。
- 不 fetch，不调用 facade，不伪造激活。所有 I/O 仍然只走 `main.ts`。

### C. 缺陷修复（均在体验层内）

1. 激活仪式误触发：改为只认点击 `[data-activate-subscription]` 后 20 秒内、订阅由未激活变为激活这一种情况。
2. toast 透底压字：改为不透明底；小窗里移到顶部。
3. 小窗 `#startErr` 挤在底栏：改为底栏上方的整行横幅。
4. 手动停止且 0 局时误弹「目标已达成」：已修正。

---

## 3. main.ts 与宿主接线

**不改契约**：bridge schema 仍为 2，没有新增 facade 方法或信号，没有新增 `update_config` 字段。契约要求的静态 ID、动态签名、SWITCHES、data-* 选择器、全局函数和 state 字段全部保留。

体验层只通过以下全局对象或 DOM 挂接，时序是：主内联脚本 → 体验层 → `main.ts`（module，最后执行）。

| 挂接点 | 方式 | 数据来源 |
|---|---|---|
| `window.applySubscription` | 包装。首次调用时置 `window.__SB_BRIDGE_READY__` 并派发 `sb-bridge-ready`；激活判定也在这里做 | `main.ts` 的 `applySnapshot()` → `applySubscription(snap.subscription)`；激活成功后也会调用 |
| `window.renderHud` | 包装。检测 running 由真变假，用于预检收尾和完成过场 | `main.ts` 的 `applyRunStatus()` 会调 `renderHud()` |
| `#btnStart` | 捕获阶段的 click 监听：未运行、未禁用、没有 `.stop` 时弹出预检层。**不拦截、不阻止** `main.ts` 自己的 click 流程（`flushConfigQueue` → `validate_preflight` → `start_run`） | — |
| `#toast` | MutationObserver 监听文本，出现「启动请求已受理」即判定预检通过 | `main.ts` 的 `start_run` 返回 ok |
| `#startErr` | MutationObserver 监听非空文本，即判定预检失败 | `main.ts` 写入的 `blocked_reason` 或 `error` |
| `#versionLabel` | MutationObserver 监听，在文本末尾追加 ` · UI-22` | `main.ts` 写入的身份信息 |
| 方案应用 | 按 UI 路径回放（点击、change 事件、`#btnSaveBonds`、Boss 与声望弹窗），由 `main.ts` 的 `afterGlobalCall` 钩子按正常路径 `pushConfig` | — |
| 本地存储 | localStorage：`sb-plans`、`sb-plan-current`、`sb-overview`、`sb-accent`、`sb-downgrade-steps`、`sb-bond-fold-set`（每位用户各自的偏好，不经后端） | — |

宿主：`WebConfigShell` 用 QWebEngine 加载 `_MEIPASS/web/dist/index.html`。`build_manifest.json` 必须由 `npm run build` 生成。小窗由 `setScene()` 设置 `body[data-win="compact"]`，`main.ts` 通过 `set_window_layout("compact", h)` 通知宿主调整到 360 宽。**局内 HUD 是原生 `overlay_hud.py`，不受本文件影响。**

---

## 4. 逐项预期（桌面正式版验收）

| 项 | 预期 |
|---|---|
| 标题 | `#versionLabel` 显示 `v0.3 · internal-pilot · <source_sha 前 12 位> · UI-22`；刷新快照后不会重复追加 |
| 启动过场 | 页面加载即出现 logo 环、名称、版本和三步勾选；收到后端第一份快照后收起，最少显示 1.2 秒，最多 8 秒；点击可跳过；系统开启「减少动态效果」时显示静态版本 |
| 预检 | 点「开始运行」后弹出摘要卡（目标、局数、策略、Boss、声望、常规、高级）和三步：连接后端 → 预检配置与订阅 → 启动脚本、接管游戏窗口。toast 显示「启动请求已受理」时第二步打勾；进入运行态后显示「已开始运行」，约 0.65 秒后收起。`#startErr` 有内容时显示「未能启动」和原因；原因含订阅或卡密时额外给「去激活」按钮。75 秒无响应显示超时。「隐藏」只关闭弹层，不中断启动 |
| 完成 | 运行从真变假、`played > 0`，并且（达到目标局数 或 阶段为 `COMPLETE`）时，出现「本轮完成」卡片：完成局数、用时、目标，以及「好的」「再来一轮」。达到目标时副标题为「目标局数已达成」，否则为「已安全停止」。手动停止且 0 局时不出现 |
| 激活 | 只有在订阅弹窗里点「激活」、20 秒内订阅由未激活变为激活时才播放仪式（SUBSCRIPTION / 订阅已激活 / 有效期）。完成卡片或预检弹层还在时，等它们收起后再播。快照里订阅状态来回翻转不会触发 |
| 小窗（蹭车、跟车，360 宽） | 布局完整、无横向滚动；toast 显示在顶部模式条下方、不透明，不压「改为跟车」；启动报错显示为底栏上方的整行横幅，可换行；「结束规则」里是「搜房：自动搜房 + 高级搜房」；「目标结束后」只有「去单刷」「去考古」，**没有「结束脚本」** |
| 看板（1080×800 / 948×898） | 无横向滚动；运行目标栏装满内容不溢出；技能卡按内容宽度排列，多余宽度分给左右两栏；羁绊两块分别贴左、贴右；日志抽屉带遮罩，空状态显示「暂无运行日志」 |

「结束脚本」由 `window.__SB_ALLOW_STOP_AFTER__` 控制，默认关闭。后端 `Settings` 接受 `hitch_after_goal="stop"` 之前不得开启。

---

## 5. 主架构差异审查建议

```powershell
cd G:\刷刷宝\GameScript-Local
git hash-object G:\刷刷宝\handoff_prompts\UI22_index.reference.html   # 应为 0d285578…
git hash-object G:\刷刷宝\handoff_prompts\UI22_index.baseline-bc228baf.html  # 应为 e974ddff…
git diff --no-index G:\刷刷宝\handoff_prompts\UI22_index.baseline-bc228baf.html G:\刷刷宝\handoff_prompts\UI22_index.reference.html   # UI-22 的改动
git diff bc228baf 6a4bba4 -- ui-v2/index.html                                     # 6a4bba4 自己的改动
```

在 6a4bba4 基础上合入第 2 节 A、B、C 三类改动。两边冲突的地方，以 6a4bba4 的业务或契约改动为准，以 UI-22 的视觉和交互改动为准。

合入后需要确认：
- `npm test` 与基线一致（看板契约 8 项全绿）；
- `npm run check`、`npm run build` 通过；
- `_verify/verify_vite_dev.py` 零外网、零控制台错误；
- 第 4 节逐项通过。

---

## 6. 验证状态与未完成项

**已验证**（云端，用 ui-v2 原版 `src/main.ts` + `mockBridge`，esbuild 打包，Chromium 渲染）：
- 启动过场、预检、运行、停止、完成、激活、小窗全流程无控制台错误；
- 契约测试结果与改动前基线一致，看板契约 8 项全绿。

**局限：**
- vitest 无法从 npm 安装，用的是替身运行器；另有 9 项失败，在改动前基线上同样失败，属于替身不支持。
- 没有跑正式 vite 构建。

**未完成：**
1. 正式 `npm test`、`npm run build` 与签名发版——需要在本机执行。
2. 桌面实机验收（第 4 节）。
3. 「降低 Y 级关卡难度」：`#downgradeSteps` **目前只存在本地**（`sb-downgrade-steps`），后端没有 `downgrade_steps` 字段。只有「失败 X 局」（`downgrade_after_failures`）真正下发到后端。
4. 「结束脚本」：需要后端支持后才能开放。
5. 局内 HUD 改版：原生 `overlay_hud.py`，不在本文件范围内。
6. 与 6a4bba4 的差异审查：由主架构负责。
