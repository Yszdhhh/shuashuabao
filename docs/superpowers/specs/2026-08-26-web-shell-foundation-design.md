# Web 壳基础（WEB-CONFIG-SHELL-FOUNDATION）设计规格

日期：2026-08-26
状态：待用户审阅
分支：`feat/web-shell-foundation-20260826`（工作树 `G:\刷刷宝\Worktrees\GameScript-WebShell-20260826`）

## 1. 目标与非目标

**目标**：把 OD12 设计沙盒（`dashboard-design-sandbox-12.html`，SHA-256 `87853c96…f2ae6f1`）原样生产化为桌面 Web 配置壳：

```
ui-v2/（Git 内，OD12 HTML 剥离沙盒外壳）
  → Vite 构建 dist/
  → QWebEngineView 加载（本地 file://，无网络）
  → QWebChannel（仅注册 DashboardFacade）
  → Settings / mode_catalog / RunnerService
```

解决原生 PySide6 仿制版的结构性分歧：字段收敛不一致、声望弹层出现原生框、多级原生弹窗卡顿、Web 已收敛字段在桌面复现。

**非目标（本阶段不做）**：
- 不迁移游戏内 HUD（`#scene-game` 的 `.game` 假游戏窗不迁移；真实 HUD 仍由原生 `OverlayHud` 负责）。
- 不重写 OD12 的 DOM/CSS/字号/弹层结构/动效；不做组件化重构（原样加载优先，组件化是后续阶段）。
- 不改局内逻辑（mediator/runtime_mediator）；不改 RunnerService 既有签名与停止链。
- 不做窗口 resize（首版固定 920×720 逻辑尺寸，frameless）。
- 不复活 api_server.py / FastAPI / Uvicorn / pywebview。

## 2. 金标与不变量

- 视觉与交互金标：`C:\Users\10639\Desktop\刷刷宝源文件\dashboard-design-sandbox-12.html`（只读参考，生产程序运行时禁止读取该目录）。
- `DESIGN-HANDOFF.md`：生产 UI 不得保留 OpenDesign chrome/预览标签/设计注释；响应式矩阵 360×800 至 1920×1080。
- 产品 token 范围 `.win/.wiz/.game-run/.game`（`--p-*` oklch 变量）；字体栈 `"Segoe UI","Microsoft YaHei UI","PingFang SC",sans-serif`（纯系统字体，无网络依赖）。
- 唯一网络依赖 `https://rsms.me/inter/inter.css` 必须移除（产品字体本就不依赖它）。
- 首阶段允许的修改仅限：删沙盒外壳、删网络字体 link、接 bridge 替换假状态/假动作。

## 3. 架构总览

```
┌─ 原生 PySide6（保留）────────────────────────────┐
│ desktop_app.py（单实例锁、AppData 迁移）          │
│ ├─ ShellRouter: SHUABAO_SHELL=web → WebConfigShell│
│ │                （默认 native → MainWindow 不动） │
│ ├─ OverlayHud / 托盘 / F12·Shift+F12 / 急停       │
│ └─ closeEvent 安全停止链                          │
├─ WebConfigShell（新增，薄）───────────────────────┤
│ QWebEngineView(frameless 宿主)                    │
│  └─ 加载 ui-v2/dist/index.html（file://）          │
│  └─ QWebChannel：仅注册 DashboardFacade            │
├─ DashboardFacade（新增，QObject，白名单 Slot）────┤
│  ├─ Settings.load/_from_dict/save + _shell 往返   │
│  ├─ mode_catalog：desktop_may_start/iter_specs    │
│  └─ RunnerService.start/stop（唯一 LIVE 入口）    │
└──────────────────────────────────────────────────┘
```

- Web 页面不接触 Mediator、文件系统、OCR、窗口句柄、游戏输入。
- 启动/停止只能经 `DashboardFacade → RunnerService`；禁止任何旁路。
- 原生 HUD/托盘/热键/急停与 Web 壳并存，共享同一 `RunnerService` 实例与停止链。

## 4. 目录结构（Git 内）

```
ui-v2/
  index.html            ← OD12 原文剥离沙盒外壳后的生产入口
  src/
    main.ts             ← 入口：初始化 bridge、绑定既有 OD12 JS 行为
    bridge/
      types.ts          ← 唯一 DTO/接口事实源（TS）
      qtBridge.ts       ← QWebChannel 实现（qrc:///qtwebchannel/qwebchannel.js）
      mockBridge.ts     ← 诚实本地假数据（浏览器开发/测试用）
  public/assets/        ← 导入时从参考 assets/ 复制；运行时唯一 UI 资产来源
  package.json / vite.config.ts / tsconfig.json

- 首阶段保留 OD12 的内嵌产品脚本，先证明原样渲染；bridge 接线阶段只替换假状态/假动作，不做组件化抽取。
- 参考 `C:\Users\10639\Desktop\刷刷宝源文件\assets\` 仅在导入时复制到 Git 内 `ui-v2/public/assets/`；生产程序只读取构建产物，不访问参考目录。 
- 业务组件不得感知 mock/Qt 环境——统一经 `bridge` 接口。

## 5. OD12 生产化边界（唯一允许的删改清单）

**删除**（沙盒外壳，来自审计 §1/§3/§4）：
- `.studio`、`.studio-bar`、`.stage`、`.canvas`、`.views`、`#btnNotes`、`.notes` 及说明表。
- `body[data-scene]` 预览路由、URL `?scene=`、localStorage `od-shuashuabao-scene`。
- `#btnStart` 的 420ms `setTimeout` 假连接；`#hudStop` 的场景回切；`#btnMin/#btnClose` 的"沙盒不最小化"toast。
- localStorage `od-shuashuabao-team-rules`（改经 bridge settings）。
- `state._log`（无消费方）。
- `#scene-game .game-view` 缺失背景图引用（`img_v3_0214k_….jpg` 不存在，不打包）。
- `recommendChallenges()` 静态推荐表改为 bridge 快照数据驱动（表可保留为展示默认，资格与数据以后端为准）。
- `<link href="https://rsms.me/inter/inter.css">`。

**保留**（产品 DOM/CSS/交互，一字不改）：
- `#scene-wizard`、`#scene-app`（chooser/farm/lead/follow/hitch 四页）、`#drawer`、`#modalLayer`、`#toast`、`#startErr`。
- 全部 `--p-*` token、920×720 布局、≤920/≤600 响应式、150ms/200ms 动效、reduced-motion、焦点管理、aria。
- 技能最多 4、优先级拖拽/↑↓、路线选择、羁绊"候选→确认→排序"、声望预算随章节变化等既有交互逻辑。
- toast 1400ms 自动隐藏、拖拽 280ms long-press（纯 UI 行为）。

**场景路由**：生产保留 `data-scene` 机制作为页内路由（wizard/chooser/farm/lead/follow/hitch），由 bridge 快照与用户操作驱动；`running` 场景不迁移（HUD 走原生）。

## 6. 桥接契约

### 6.1 DashboardFacade（QObject，QWebChannel 唯一注册对象）

全部方法 `@Slot(str) -> str`，入参出参均为 JSON 字符串；未列方法不存在。

| 方法 | 入参 | 出参 |
|---|---|---|
| `get_snapshot()` | — | `SnapshotDTO` |
| `update_config(patch)` | Settings 字段白名单 patch | `{ok, errors[], settings}` |
| `update_shell(patch)` | `{theme?, selected_mode_id?}` | `{ok, errors[], shell}` |
| `validate_preflight(mode_id)` | — | `PreflightDTO` |
| `start_run(mode_id)` | — | `{ok, error?}` |
| `stop_run()` | — | `{ok, error?}` |
| `window_control(action)` | `"minimize"\|"close"` | `{ok}` |

Qt Signals（QWebChannel 自动暴露，JS `signal.connect(...)`）：
- `snapshot_changed(str json)`
- `run_status_changed(str json)`
- `log_appended(str text, str level)`

### 6.2 DTO（types.ts 为唯一事实源，Python 侧结构一一对应）

```ts
interface SnapshotDTO {
  settings: SettingsDTO;          // asdict(Settings) − PERSIST_DENYLIST，全字段
  shell: ShellDTO;                // { theme: "light"|"dark", selected_mode_id: string }
  modes: ModeDTO[];
  run: RunStatusDTO;
}
interface ModeDTO {
  id: string; label: string;
  startable: boolean;             // desktop_may_start(id)（用户 2026-08-26 决策：布尔判定，证据不作门禁）
  evidence_status: string;        // live_partial | video_detail_no_click | skeleton | live_cli
  badge: string;                  // badge_text(spec)
  blocked_reason: string;         // 不可启动时的原因，可空
  visible_settings: string[];
}
interface RunStatusDTO {
  state: "IDLE"|"STARTING"|"RUNNING"|"STOPPING"|"COMPLETE"|"FAILED";
  mode_id: string | null;
  phase: string; game_count: number; cycle_num: number;
  terminal_reason: string; ocr_status: string; last_action: string;
}
interface PreflightDTO {
  ok: boolean; blocked_reason: string;
  checks: { id: string; ok: boolean; detail: string }[];
  // checks: mode_enabled / live_lock / skills_non_empty(≤4) / cycle_valid / follow_pair_code(≤24)
}
```

### 6.3 行为规则

- `update_config`：`Settings._from_dict(patch, fallback=current)` 做类型/范围/枚举/技能≤4 清洗；非法字段不落盘并返回 `errors`；保存 = `{**collect_persistable_settings(s), "_shell": 现有 _shell 原样往返}`（防 `_shell` 孤儿化——审计风险 #3）。
- `validate_preflight`：`desktop_may_start` + `live_lock_busy(app_data)` + 技能 1..4 非空 + 循环次数为有效整数 + `follow_pair_code ≤24` 字符。OCR 依赖失败映射为 check 失败（`ocr_unavailable`），不静默。
- `start_run`：先内部 `validate_preflight`，失败返回 `{ok:false}`；成功调 `runner.start(mode_id, settings)` 并 `worker.start()`；`worker.signals` 以 QueuedConnection 桥到 facade 信号。
- 运行态轮询：facade `QTimer` 400ms 读 `runtime_status_from_mediator(worker.mediator)`（与原生 `_poll_runtime` 同模式、同竞争语义，审计风险 #5 记录在案）。
- `stop_run`/`window_control("close")`：一律进入 `runner.stop()` 与原生 closeEvent 链；Web 崩溃不影响该链（见 §8）。
- `follow_team`/`lobby_hitch` 保持 `startable=true`（用户 2026-08-26 决策：后续真机测试需要可启动入口）；`evidence_status` 徽标如实展示，不冒充满绿。

## 7. ui-v2 前端

- `main.ts`：启动时 `get_snapshot()` 初始化 OD12 `state`，随后所有渲染走既有 OD12 函数；用户操作产生 intent → `bridge.update_config/update_shell/start_run/stop_run`；信号回推 → 重渲染。
- `qtBridge.ts`：注入 `qrc:///qtwebchannel/qwebchannel.js`，`new QWebChannel(qt.webChannelTransport, ...)`；超时/失败显式报错页，不静默降级 mock。
- `mockBridge.ts`：仅 Vite dev/浏览器测试用，数据形状与 types.ts 完全一致；生产构建不打包（`import.meta.env.MODE` 分支）。
- 假状态替换点（审计 §7）：`refreshSummary/renderLaunchSummary/renderHud/renderGames/renderTeamRules` 改快照渲染；`btnStart` 走 `validate_preflight → start_run`；`btnMin/btnClose` 走 `window_control`。

## 8. QWebEngine 宿主（WebConfigShell）

- `QWebEngineView` + frameless 固定尺寸窗口（920×720 逻辑，Qt DPI 缩放）；标题栏拖动经 `window_control` 扩展 `startSystemMove`（titlebar mousedown → facade）。
- 仅允许 `file://`（指向 dist）与 `qrc://` 导航；`createWindow`/外部链接/下载一律拒绝；生产禁开发者工具。
- CSP meta：`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'`。
- `renderProcessTerminated`：显示原生错误页+重载按钮；RunnerService/HUD/急停不受影响（不同对象，无共享状态）。
- 环境缺 QtWebEngine 时显式报错退出（`ModuleNotFoundError` 不静默回退原生）。

## 9. 入口与原生职责

- `desktop_app.py`：`SHUABAO_SHELL=web` 时构造 `WebConfigShell(app_data, root)`，否则现有 `MainWindow`；锁、迁移、异常钩子共用。默认 native，快捷方式不受影响。
- 原生保留：`OverlayHud`、托盘、F12/Shift+F12、急停、closeEvent 安全停止、游戏窗口定位。
- 禁止导入/启动 `api_server.py`、FastAPI、Uvicorn、pywebview（入口测试断言）。

## 10. AppData 统一（前置小修，随本分支交付）

- `player_profile.py::default_profile_dir()` → `paths.player_profile_dir()`；`default_live_lock_path()` → `paths.live_lock_path()`。两处当前指向 `profile/`（单数），磁盘从未生成，无迁移负担。
- `logs/` 目录归属待实现期核对（AppData 磁盘存在 `logs/` 但 provider 未定义），如分裂则同法收编。

## 11. 打包

- `requirements-desktop.txt`：`PySide6-Essentials` → `PySide6`（完整版，含 WebEngine；用户已确认 +150MB 可接受）。
- `ShuaBao.spec`：`hiddenimports += ["PySide6.QtWebEngineWidgets","PySide6.QtWebEngineCore","PySide6.QtWebChannel"]`；`datas += [("ui-v2/dist","web/dist")]`；PyInstaller 6.22 hook 自动收集 `QtWebEngineProcess.exe`/`resources/*.pak`/`icudtl.dat`/locale paks（Qt 审计已确认 hook 存在）。
- 构建脚本：打包前先 `npm ci && npm run build`（Node 仅构建机需要，运行时零 Node/零网络）。
- 冷启动验收：断网 + 无 Node 环境 + 无桌面参考目录访问。

## 12. 测试策略

Python（pytest，复用现有夹具）：
- `test_dashboard_facade.py`：白名单方法面、DTO 形状、patch 校验（非法类型/超范围/超长 pair_code/技能>4 拒绝且不落盘）、`_shell` 往返、preflight 真实调用 `desktop_may_start`/`live_lock_busy`、start 仅经 `RunnerService.start`（monkeypatch 断言）、stop 仅经 `runner.stop()`。
- `test_web_config_shell.py`：QWebChannel 仅注册 facade；导航拦截；渲染进程崩溃后 runner 仍可 stop；入口无 fastapi/uvicorn/webview/api_server 导入。
- 既有 `tests/test_desktop_app.py`（108 passed 基线）不回归。

前端：`vitest` 覆盖 mockBridge 数据形状与 state→DTO 映射；`tsc --noEmit`；`vite build` 零网络。

视觉验收（ox-alpha，非 v4flash）：真实桌面截图 1000×780 与 860px 宽、100%/125%/150% DPI，对照 OD12 参考渲染，覆盖 farm/follow/hitch/声望弹层/抽屉/深浅主题。

## 13. 风险与既知限制

| 风险 | 处置 |
|---|---|
| frameless 固定尺寸不可 resize | 首版明确限制；resize 需 `startSystemResize`，后续阶段 |
| `_poll_runtime` 无锁跨线程读 | 与原生同语义，审计在案；不新增风险 |
| live.lock 与原生实例竞争 | preflight `live_lock_busy` 前置拦截 |
| QtWebEngine 打包体积/资源遗漏 | hook 自动收集 + 冷启动验收覆盖 |
| OD12 `recommendChallenges` 静态表 | 展示默认保留，资格判定全部后端化 |
| follow_team 证据不足但可启动 | 用户明示决策（真机测试入口）；徽标如实显示 skeleton |

## 14. 首批交付验收（用户指定）

1. 设置读写：改→保存→重启→保留；非法 patch 不落盘。
2. 真实预检：门禁/锁/字段检查真实生效。
3. 学习模式（dry_run）安全启动与停止，零真实输入。
4. 运行状态与日志回传到页面。
5. 最小化/关闭走原生链，急停可用。
6. 打包后无黑屏冷启动（断网）。
7. 100%/125%/150% 缩放截图对比通过。
