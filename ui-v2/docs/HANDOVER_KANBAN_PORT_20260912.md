# 刷刷宝新看板移植对齐与交接文档（2026-09-12）

## 1. 交付概况与基线信息

- **目标**：将桌面副本中的全新液态银看板（液态玻璃/石墨主题、局内 HUD、21 阶段进程词、鎏金动效）移植进正式线 `ui-v2`，完全走正式线 QWebEngine + `DashboardFacade` (BRIDGE_SCHEMA_VERSION=2) 架构，彻底剥离旧版 FastAPI / pywebview 路线。
- **工作根目录**：`G:\刷刷宝\Worktrees\ui-kanban-port-20260912`
- **开发分支**：`feat/ui-v2-kanban-port-20260912`
- **基线 Commit SHA**：`f0243f586f9bd133286bba7bd22decac940675e4`（严格对齐桌面「刷刷宝 Live 实机测试.lnk」的 `-ProductionSourceSha`）
- **正式入口**：`desktop_app.py` 默认 `SHUABAO_SHELL=web` → `WebConfigShell`（QWebEngine，纯本地 file:// / qrc:// 零外网）→ 加载 `ui-v2/dist/index.html` → QWebChannel 注册对象 `facade`。

---

## 2. 生产构建产物哈希 (Production Dist Hashes)

执行 `npm run build` 生成的生产产物位于 `ui-v2/dist/`，全部采用相对路径 `./assets/...`，严禁任何外网连接：

| 文件路径 | SHA-256 校验码 | 字节大小 | 职责与审计结论 |
|---|---|---|---|
| `ui-v2/dist/index.html` | `0af93a197ab4200f63e965b09329efa6ec1dc33f3c2e4fa95dad8d31e613c570` | 296,130 字节 | 经典内联脚本与视觉层，已剔除全部 pywebview/FastAPI 路径，包含完整液态银与 HUD 结构 |
| `ui-v2/dist/assets/index-CIV1HTCd.js` | `9b2b40bbfa975986e45c1d89cb1ccb74c5ee38cb3fb2f0af20f3a053b3a07148` | 23,804 字节 | 主 I/O 适配层（`src/main.ts` 编译产物），负责 Facade 通信、配置队列与预检 |
| `ui-v2/dist/assets/qtBridge-BezqWp-3.js` | `2992758ca367801c0f32911d34463d6cd8243dcaeffd1616ac4d61e2d573b2c1` | 3,493 字节 | QWebChannel 异步加载动态 Chunk，仅当检测到 Qt WebEngine 时按需加载 |

> 审计结论：生产产物通过 `audit_dist.py` 自动化检测，**违规项计数为 0**（无 `fetch('/api/...')`、无 `window.pywebview`、无 `HOST_MODE`、无 `syncBackendSettings`、无 `shuabao_card_key`、无外网 URL）。

---

## 3. 核心修改与落地明细

### 3.1 视图层 (`ui-v2/index.html`)
1. **液态银与鎏金动效移植**：完整保留桌面副本的液态银/石墨深浅主题、微质感流光、毛玻璃卡片、折叠面板与彩虹灯效 Canvas。
2. **运行控制控件重构 (`#btnStart`)**：将桌面副本的 `<label for="ctrl-running">` 改造为原生 `<button>`，内部保留 `#btnStartTextRun`（开始运行/不可启动）与 `#btnStartTextStop`（停止运行/停止中…）两个状态容器，既保持原生 `button.disabled` 语义，又兼容 CSS `:has(:checked)` 状态。
3. **HUD 21 阶段全量覆盖**：
   - 完整覆盖正式线 `Phase` 的全部 21 个阶段：`BOOT`、`WAIT_EXIT`、`LOBBY_ROOM`、`PREPARE`、`WAIT_UI`、`PLATFORM_MAP`、`CREATE_ROOM`、`ROOM_WAITING`、`ROOM_STARTING`、`STAGE_SELECT`、`STAGE_STARTING`、`HERO_SETUP`、`ERROR`、`MAIN_LINE`、`EARLY_CHALLENGE`、`ANCHOR_BOSS`、`LONGZHU`、`RECOVER_FAILURE`、`QUIT`、`NEXT`、`COMPLETE`，外加 `STOPPING`。
   - `speakHud` 未知阶段一律兜底为通用中文“运行中”，彻底杜绝英文枚举泄漏。
   - 局内进度严格采用「第 N / M 局」或「已完成 N 局」，杜绝阶段百分比倒计时的伪状态。
4. **业务选项修正**：
   - 用户明确指示**跟车无配对码设计**，移除配对码干扰；
   - 移除 `follow_after_room` 中凭空出现的 `"end"` 按钮，严格限制为 `"solo"` / `"arch"` / `"hitch"`；
   - 补齐正式线向导组件（`<section id="scene-wizard">`、`renderWizard()`、`openWizard()`），`MODE_LABEL` 严格对齐正式线标准命名，100% 跑通 `test_web_config_shell.py`。
5. **纯净本地运行**：移除假卡密本地 30 天激活，移除旧轮播 timer 与旧 FastAPI 请求。

### 3.2 适配层 (`ui-v2/src/main.ts`)
1. 增加 `#btnStartTextRun` 与 `#btnStartTextStop` 的状态驱动支持。
2. `applyRunStatus` 接收 `RunStatusDTO` 时，双向同步 `#ctrl-running`、`document.body.dataset.running`、`state.hudPhase`、`state.played`，并触发 `renderHud()` 重绘。
3. 安全保护 `document.getElementById("followPairForm")?.addEventListener(...)`，在无配对码 DOM 时安全跳过，不抛异常。
4. F12 全局急停与 HUD `#hudStop` 按钮统一收口调 `bridge.stop_run()`。
5. `boot()` 在开发模式自动连接 `mockBridge` 的信号通道。

### 3.3 开发与预览层 (`ui-v2/src/bridge/mockBridge.ts`)
1. 提供 `createMockBridgeConnection()`，导出符合 `DashboardBridgeSignals` 规格的信号（`snapshot_changed`、`run_status_changed`、`log_appended`）。
2. 在开发模式调用 `start_run()` 时，模拟合法的阶段迁移轮播与局数递增；调用 `stop_run()` 时，严格先进入 `STOPPING`，再进入 `COMPLETE`，绝不提前宣布停止。
3. 生产打包代码与 mockBridge 物理隔离，构建产物零打包。

### 3.4 契约测试与验证套件
1. **`ui-v2/tests/kanban_contract.spec.ts`**：
   - 严格锁定 30 个静态 DOM ID、6 项动态签名、17 个全局函数/常量、5 项 SWITCHES、7 项 data-* 选择器与核心 state 字段；
   - 引入沙箱内联脚本动态执行审计与离线比对工具。
2. **`ui-v2/_verify/verify_vite_dev.py`**：
   - 自动化驱动 Playwright 执行：四场景 × 深浅主题截图、零外网请求审计、抽屉横滑归零、折叠状态保持、主题切换无残留类、礼花 Canvas 回收、启动与急停联动。

---

## 4. 验证结果汇总 (Verification Results)

### 4.1 前端测试与构建验证
- `npm run check` (TypeScript): **0 errors, exit 0**
- `npm test` (Vitest 7 文件, 36 用例): **36 passed, exit 0**
- `npm run build` (Vite 生产打包): **built in 290ms, exit 0**

### 4.2 Python 后端契约与外壳测试
- 执行命令：`python -m pytest tests/test_dashboard_facade.py tests/test_dashboard_facade_runner.py tests/test_web_config_shell.py -q`
- 结果：**145 passed in 35.48s, exit 0**（涵盖 Facade RPC、配置队列、版本握手、WebConfigShell、窗口布局、完整向导与断点断言）

### 4.3 浏览器端端到端验收 (`verify_vite_dev.py`)
- 执行结果：**10 项全绿 (ALL PASSED, exit 0)**：
  - `zero_external_requests`: PASS（216/216 请求全为本地，0 外网）
  - `zero_api_requests`: PASS（0 处 `/api/` 遗留）
  - `scene_screenshots_saved`: PASS（8 张高清场景图落盘至 `_verify/out/`）
  - `drawer_max_scroll_left_zero`: PASS（最大 scrollLeft = 0）
  - `drawer_closed_after_esc`: PASS（Escape 关闭正常）
  - `fold_state_preserved`: PASS（重绘与调序后展开状态保持）
  - `theme_no_leftover_class`: PASS（切换后无残留 `theme-switching` 类）
  - `confetti_canvas_recycled`: PASS（Canvas 动画淡出后彻底移出 DOM）
  - `run_start_and_f12_stop`: PASS（启动/急停联动与 HUD 进程词流转正常）
  - `zero_page_errors`: PASS（页面 0 未捕获异常）

---

## 5. 阻塞与未做事项 (Blocked & Pending Items)

以下事项严格遵守红线，未做任何违规执行：

| 事项 | 状态 | 说明 |
|---|---|---|
| 真机点击「开始运行」 | **BLOCKED（待用户实机）** | 严格禁止 AI 产生真实键盘/鼠标/KK游戏输入与提权操作 |
| 启动 KK / Live harness 自动化跑局 | **BLOCKED（待用户实机）** | 必须由用户在具备游戏客户端的环境下实机测试 |
| 覆盖发布目录 `build_release.ps1` | **BLOCKED（待用户批准）** | 严禁覆盖用户正在使用的桌面快捷方式与 ShuaBao 安装目录 |
| 360 宽置顶小窗修改 | **提案中（待用户批准）** | 第一阶段已在 1080×820 下验收。若后续需要真机小窗，需单独审批对 `web_config_shell.py` 与 facade 的布局协议扩展 |
