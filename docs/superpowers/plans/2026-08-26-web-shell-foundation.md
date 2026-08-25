# Web 壳基础（WEB-CONFIG-SHELL-FOUNDATION）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OD12 沙盒原样生产化为 QWebEngine 桌面配置壳，经 QWebChannel 白名单 facade 接 Settings/mode_catalog/RunnerService。

**Architecture:** 见规格 §3。原生保留 HUD/托盘/热键/急停；Web 壳经 `DashboardFacade`（唯一注册对象）读写配置与启停。

**Tech Stack:** PySide6(QtWebEngine/QtWebChannel) · Vite+TS · pytest · vitest

**Spec:** `docs/superpowers/specs/2026-08-26-web-shell-foundation-design.md`（DTO/边界/验收以规格为准，计划不重复）

## Global Constraints

- OD12 金标 SHA-256 `87853c96…f2ae6f1`；仅允许规格 §5 删改清单。
- 生产运行零网络、零 Node、零桌面参考目录读取。
- LIVE 只经 `RunnerService.start/stop`；禁止 fastapi/uvicorn/webview/api_server。
- 快捷方式与默认 native 路径不变；`SHUABAO_SHELL=web` 才进 Web 壳。
- 测试不启动真实游戏、不发真实输入；dry_run only。
- 视觉任务派 ox-alpha；实现派 task agent；主会话验收。

---

### Task 0: 分支基线提交

**Files:** 全部 overlay 快照（154 个未提交文件）

- [ ] `git add -A && git commit -m "chore: snapshot native shell baseline (trial-merge working state)"`
- [ ] 验证 `git status` 干净；主工作树 `trial-merge` 不受影响

### Task 1: AppData provider 收编

**Files:**
- Modify: `src/shuabao/player_profile.py:77-82`（default_profile_dir/default_live_lock_path → paths provider）
- Test: `tests/test_player_profile.py`

**Interfaces:** `default_profile_dir() == paths.player_profile_dir()`；`default_live_lock_path() == paths.live_lock_path()`

- [ ] 失败测试：两函数返回值与 provider 相等（含 `SHUABAO_APP_DATA` 覆盖场景）
- [ ] 实现：函数体改调 `paths.player_profile_dir()/live_lock_path()`，删除 `LIVE_LOCK_NAME` 本地拼接
- [ ] `pytest tests/test_player_profile.py tests/test_app_data_paths.py -q` 全绿
- [ ] commit `fix(appdata): route player_profile through canonical paths provider`

### Task 2: ui-v2 脚手架 + OD12 原样迁移（Agent A）

**Files（全部新建）:** `ui-v2/{package.json,vite.config.ts,tsconfig.json,index.html,src/main.ts,src/od12/*,src/bridge/types.ts,src/bridge/mockBridge.ts,public/assets/**}`

- [ ] 复制 OD12 HTML → `ui-v2/index.html`；仅执行规格 §5 删改清单（studio-bar/notes/stage/canvas/views、`?scene=`、localStorage scene/team-rules、420ms setTimeout、rsms link、`state._log`、`.game-view` 缺失背景图）
- [ ] OD12 内嵌 JS 迁入 `src/od12/`（原逻辑，仅按 §7 替换点改为 bridge 调用；本任务先接 mockBridge）
- [ ] `types.ts` 按规格 §6.2 逐字定义；`mockBridge.ts` 诚实数据（形状=types.ts）
- [ ] assets 映射：`assets/Images/{skills,factions,boss,chuanjiaobao}` + branding logo → `public/assets/…` 对应 OD12 相对路径
- [ ] `npm ci && npm run build && tsc --noEmit` 离线通过；`vite preview` 手动核对 farm/follow/hitch/声望弹层渲染
- [ ] vitest：mockBridge 数据形状 = types.ts（一个文件即可）
- [ ] commit `feat(ui-v2): OD12 production shell scaffold (sandbox chrome stripped)`

### Task 3: DashboardFacade 配置面（Agent B，与 A 并行）

**Files（全部新建）:** `src/shuabao/shell/dashboard_facade.py`、`tests/test_dashboard_facade.py`

**Interfaces（消费）:** `Settings.load/save/_from_dict`、`mode_catalog.{iter_specs,desktop_may_start,badge_text,collect_persistable_settings}`、`paths.user_settings_path`、`live_lock_busy`
**Interfaces（产出，Task 4/6 依赖）:** 规格 §6.1 七个 Slot + 三信号；`facade.get_snapshot()/update_config/update_shell/validate_preflight` 可独立调用（无 QWebEngine 依赖，QObject 即可）

- [ ] 失败测试：白名单方法面（`dir` 过滤断言无非白名单公有方法）；DTO 形状；patch 校验（非法类型/技能>4/pair_code>24/循环非整数 → errors 且磁盘不变）；`_shell` 往返（预置 _shell → update_config → _shell 原样）；preflight 调用真实 `desktop_may_start`+`live_lock_busy`（monkeypatch 断言）；`get_modes()` 返回 5 模式且 follow/hitch `startable=true`、lab `startable=false`
- [ ] 实现最小 facade（配置面四方法 + 信号声明；start/stop 留 Task 4）
- [ ] `pytest tests/test_dashboard_facade.py -q` 绿；commit `feat(shell): dashboard facade config surface (whitelist JSON DTO)`

### Task 4: Facade 运行控制（依赖 Task 3）

**Files:** Modify `dashboard_facade.py`、`tests/test_dashboard_facade.py`

- [ ] 失败测试：`start_run` 前置 preflight 失败→`{ok:false}` 不建 worker；成功→monkeypatch `RunnerService.start` 断言唯一调用路径+`worker.start()`；`stop_run`→`runner.stop()`；worker 信号→facade 信号（QueuedConnection）；400ms 轮询读 `runtime_status_from_mediator`
- [ ] 实现 `start_run/stop_run` + 信号桥 + QTimer 轮询
- [ ] 测试绿；commit `feat(shell): facade run control via RunnerService`

### Task 5: qtBridge + main.ts 接线（依赖 Task 2）

**Files:** `ui-v2/src/bridge/qtBridge.ts`、`ui-v2/src/main.ts` 及 od12 替换点

- [ ] qtBridge：`qrc:///qtwebchannel/qwebchannel.js` 注入+超时报错页；三信号订阅→快照重渲染；七方法调用
- [ ] main.ts：启动 `get_snapshot()` 初始化 state；btnStart→`validate_preflight→start_run`；btnMin/btnClose→`window_control`；`startErr/toast` 承载 bridge 错误
- [ ] `tsc --noEmit && npm run build` 绿；vitest 更新；commit `feat(ui-v2): qt bridge wiring replaces sandbox fakes`

### Task 6: WebConfigShell 宿主 + 入口（依赖 Task 4、5）

**Files:** 新建 `src/shuabao/shell/web_config_shell.py`、`tests/test_web_config_shell.py`；Modify `desktop_app.py`（SHUABAO_SHELL 分支）

- [ ] 失败测试：QWebChannel 仅注册 facade；导航仅 file/qrc；`renderProcessTerminated` 后 `runner.stop()` 仍可达；入口 web 分支无 fastapi/uvicorn/webview/api_server 导入；缺 QtWebEngine 显式报错
- [ ] 实现：frameless 920×720、CSP、`window_control`→`startSystemMove`/close 链、崩溃恢复页
- [ ] `pytest tests/test_web_config_shell.py tests/test_desktop_app.py -q` 绿；commit `feat(shell): qwebengine host shell + entry switch`

### Task 7: 打包接线（依赖 Task 6）

**Files:** Modify `requirements-desktop.txt`、`ShuaBao.spec`、构建脚本

- [ ] `PySide6-Essentials`→`PySide6`；spec hiddenimports+datas(`ui-v2/dist→web/dist`)
- [ ] 构建脚本前置 `npm ci && npm run build`
- [ ] PyInstaller 构建成功；断网冷启动冒烟（无黑屏、页面加载、native 停止可用）
- [ ] commit `build: bundle qtwebengine runtime + ui-v2 dist`

### Task 8: 验收（依赖 Task 7）

- [ ] 隔离 AppData（`SHUABAO_APP_DATA`）跑 Web 壳：设置读写往返、预检、dry_run 启停、状态/日志回传、最小化/关闭
- [ ] ox-alpha 截图：1000×780 与 860px、100%/125%/150% DPI，对照 OD12（farm/follow/hitch/声望弹层/抽屉/深浅主题）
- [ ] scoped pytest 全绿 + `tools/release_gate.py`（记录真实结果，不改基线）
- [ ] 交付报告（含截图与失败清单）

## Self-Review

- 规格覆盖：§5→Task 2；§6→Task 3/4/5；§8/§9→Task 6；§10→Task 1；§11→Task 7；§12/§14→Task 8。无缺口。
- 类型一致性：facade 七 Slot/三信号名与规格 §6.1 一致；`startable` 语义（布尔门禁）Task 3 测试断言。
- 无占位符；接口块给出精确签名来源（规格 §6）。
