# 刷刷宝 UI-V2 看板架构与接口契约清单（2026-09-12）

> **目标**：将桌面副本中的全新液态银看板（液态玻璃/石墨主题、局内 HUD、进程词、鎏金动效）移植进正式线 `ui-v2`，完全走正式线 QWebEngine + `DashboardFacade` (BRIDGE_SCHEMA_VERSION=2) 架构，彻底剥离旧版 FastAPI / pywebview 路线。  
> **基线环境**：
> - 权威基线工作树：`G:\刷刷宝\Worktrees\prod-source-3904913-20260911`（HEAD: `f0243f5`）
> - 本开发工作树：`G:\刷刷宝\Worktrees\ui-kanban-port-20260912`（分支: `feat/ui-v2-kanban-port-20260912`）
> - 桌面新看板源文件：`C:\Users\10639\Desktop\影音游戏\GameScript-Local\ui-v2\index.html`（SHA256: `3D6E8381E75AF0F3A266E2240A42F092EBFC9E3DE4F7E6D473945CE0E97231CC`，306,562 字节）

---

## 1. 架构拓扑与边界划分

正式线 `ui-v2` 采用 **双层解耦架构**：
1. **视图层 (`index.html`)**：经典 HTML/CSS/JS 内联脚本，暴露全局视图状态（`state`）、预设数据（`BUILDS`、`FACTIONS`、`STAGE_MAX`）以及全局渲染函数（`renderChapterStage`、`renderBuilds`、`renderBonds` 等）。**纯本地界面渲染，严禁包含任何直接的后端 API 请求（如 `fetch('/api/...')`）或伪造的授权激活。**
2. **I/O 适配层 (`src/main.ts`)**：唯一的系统 I/O 出口。通过 QWebChannel 连接宿主唯一的注册对象 `facade`（`DashboardFacade`），管理配置队列（`config_queue.ts`）、模式映射、启动预检（`validate_preflight`）与任务启停（`start_run` / `stop_run`）。

---

## 2. 全量契约对照矩阵 (Contract Matrix)

### 2.1 全局函数与变量契约 (Globals & Functions)

`src/main.ts` 通过 `declare` 或 `afterGlobalCall` 挂钩并依赖的全局对象与函数：

| 契约符号 | 类型 | 依赖方式 | 职责说明 | 正式线基线 | 桌面新看板 | 对照结论与改动要求 |
|---|---|---|---|---|---|---|
| `state` | `object` | `declare const` / 读写 | 全局响应式状态树 | 存在 | 存在 | **已有且一致**。新看板补充了 `folds`、`running`、`hudPhase` |
| `BUILDS` | `array` | `declare const` | 官方推荐流派列表 | 存在 | 存在 | **已有且一致** |
| `FACTIONS` | `array` | `declare const` | 声望阵营定义表 | 存在 | 存在 | **已有且一致** |
| `STAGE_MAX` | `object` | `declare const` | 各章节最大关卡数字典 | 存在 | 存在 | **已有且一致** |
| `$` | `function` | `declare function` | `id => document.getElementById(id)` | 存在 | 存在 | **已有且一致** |
| `toast` | `function` | `declare function` | 轻量浮层信息提示 | 存在 | 存在 | **已有且一致** |
| `setSwitch` | `function` | `declare function` | 开关控件开闭动画与状态切换 | 存在 | 存在 | **已有且一致** |
| `setScene` | `function` | `declare` + `afterGlobalCall` | 场景切换核心入口 | 存在 | 存在 | **已有且一致**。注意：新看板将向导归纳为顶栏模式条 |
| `setCycle` | `function` | `declare` + `afterGlobalCall` | 目标局数数值变更 | 存在 | 存在 | **已有且一致** |
| `refreshSummary`| `function` | `declare` + `afterGlobalCall` | 刷新状态栏与启动按钮可用性 | 存在 | 存在 | **已有且一致** |
| `renderChapterStage` | `function` | `declare` + `afterGlobalCall` | 章节与关卡渲染 | 存在 | 存在 | **已有且一致** |
| `renderBuilds` | `function` | `declare function` | 流派列表与自定义列表渲染 | 存在 | 存在 | **已有且一致** |
| `renderBonds` | `function` | `declare function` | 羁绊/发育/卡组卡片渲染 | 存在 | 存在 | **已有且一致** |
| `renderNegatives` | `function` | `declare` + `afterGlobalCall` | 特殊宝物（负面）勾选列表渲染 | 存在 | 存在 | **已有且一致** |
| `renderPrestige` | `function` | `declare function` | 声望分配面板与点数渲染 | 存在 | 存在 | **已有且一致** |
| `renderTeamRules` | `function` | `declare function` | 组队跟车/蹭车规则与路径渲染 | 存在 | 存在 | **已有且一致** |
| `renderNames` | `function` | `declare function` | 传家宝与三国战线Boss名称回显 | 存在 | 存在 | **已有且一致** |
| `currentSkills` | `function` | `declare function` | 提取当前选中的 1~4 个技能代码 | 存在 | 存在 | **已有且一致** |
| `applyOfficial` | `function` | `declare function` | 应用官方流派预设 | 存在 | 存在 | **已有且一致** |
| `renderSkillRank` | `function` | `afterGlobalCall` | 技能优先级拖拽/排序渲染 | 存在 | 存在 | **已有且一致** |
| `renderWizard` | `function` | `afterGlobalCall` | 旧向导视图渲染 | 存在 | 存在（占位）| **已有**。向导在新看板中已融入顶栏 `tabSolo` 等快捷切换 |
| `applySubscription` | `function` | `window.applySubscription` | 订阅有效性回显 | 存在 | 存在 | **语义变化**。新看板含前端假激活，移植时需对接真实 DTO |
| `openSubscriptionModal`| `function` | `window.openSubscriptionModal`| 打开卡密激活弹窗 | 存在 | 存在 | **已有且一致** |

---

### 2.2 静态 DOM ID 契约 (Static DOM IDs)

`src/main.ts` 在初始化事件绑定或 UI 回显时直接获取的静态节点：

| DOM ID | 元素类型 | 所在区域 | 职责说明 | 正式线基线 | 桌面新看板 | 对照结论与改动要求 |
|---|---|---|---|---|---|---|
| `scene-app` | `div` | 根容器 | 主应用视窗根节点，挂载主题属性 | 存在 | 存在 | **已有且一致** |
| `versionLabel` | `span` | 顶栏 | 显示应用版本与当前构建 SHA | 存在 | 存在 | **已有且一致** |
| `subscriptionPill` | `div/span` | 顶栏 | 订阅状态与授权指示胶囊 | 存在 | 存在 | **已有且一致** |
| `evidencePill` | `span` | 顶栏 | 构建证据完整性指示胶囊 | 存在 | 存在 | **已有且一致** |
| `identityPill` | `span` | 顶栏 | 详细构建身份信息胶囊 | 存在 | 存在 | **已有且一致** |
| `statusPill` | `div` | 顶栏 | 运行状态胶囊（待命/运行中等） | 存在 | 存在 | **已有且一致** |
| `btnMin` | `button` | 顶栏 | 窗口最小化按钮 | 存在 | 存在 | **已有且一致** |
| `btnClose` | `button` | 顶栏 | 窗口关闭按钮 | 存在 | 存在 | **已有且一致** |
| `btnTheme` | `button` | 顶栏 | 深浅主题切换按钮 | 存在 | 存在 | **已有且一致** |
| `gamesToday` | `strong` | 统计栏 | 今日已完成局数文本节点 | 存在 | 存在 | **已有且一致** |
| `gamesCap` | `span` | 统计栏 | 目标局数上限文本节点 | 存在 | 存在 | **已有且一致** |
| `lamp` | `div` | 底栏控制 | 启动就绪指示灯容器 | 存在 | 存在 | **已有且一致** |
| `lampText` | `span` | 底栏控制 | 启动就绪状态文本（预检通过等） | 存在 | 存在 | **已有且一致** |
| `startErr` | `span` | 底栏控制 | 预检阻断/启动失败原因提示文本 | 存在 | 存在 | **已有且一致** |
| `btnStart` | `button/label` | 底栏控制 | 任务启动/停止主按钮 | `<button>` | `<label>` | ⚠️ **改名/类型变异**。见 3.1 节详细分析 |
| `loadBar` | `div` | 顶栏/HUD | 运行中骨架呼吸进度条 | 存在 | 存在 | **已有且一致** |
| `btnActivateKey` | `button` | 底栏/抽屉 | 唤起卡密激活弹窗按钮 | 存在 | 存在 | **已有且一致** |
| `skillRank` | `div` | 技能面板 | 技能优先级卡片列表容器 | 存在 | 存在 | **已有且一致** |
| `bonds` | `div` | 羁绊面板 | 羁绊及卡组卡片容器 | 存在 | 存在 | **已有且一致** |
| `negatives` | `div` | 抽屉 | 特殊宝物（负面）勾选列表容器 | 存在 | 存在 | **已有且一致** |
| `roomName` | `input` | 抽屉/组队 | 自建房间名称输入框 | 存在 | 存在 | **已有且一致** |
| `roomPass` | `input` | 抽屉/组队 | 自建房间密码输入框 | 存在 | 存在 | **已有且一致** |
| `followPairForm` | `form` | 跟车页面 | 带车端配对表单 | 存在 | **缺失** | ❌ **新看板缺失**。会导致 `main.ts` 初始化抛出 null 异常 |
| `followPairCode` | `input` | 跟车页面 | 跟车端配对码输入框 | 存在 | **缺失** | ❌ **新看板缺失**。需补充并适配液态银样式 |
| `btnHitchAdvanced` | `button` | 蹭车页面 | 高级搜房弹窗唤起按钮 | 存在 | 存在 | **已有且一致** |
| `swSecret` | `button` | 抽屉 | 自动进入秘境开关 | 存在 | 存在 | **已有且一致** |
| `swCloseML` | `button` | 抽屉 | 自动提前结束主线开关 | 存在 | 存在 | **已有且一致** |
| `swAutoArch` | `button` | 抽屉 | 自动考古开关 | 存在 | 存在 | **已有且一致** |
| `swNewRoom` | `button` | 抽屉 | 每局新建房间开关 | 存在 | 存在 | **已有且一致** |
| `swDragon` | `button` | 抽屉 | 优先寻找龙珠开关 | 存在 | 存在 | **已有且一致** |
| `modalLayer` | `div` | 浮层 | 模态弹窗遮罩层根节点 | 存在 | 存在 | **已有且一致** |
| `modalSheet` | `div` | 浮层 | 模态弹窗内容挂载容器 | 存在 | 存在 | **已有且一致** |

---

### 2.3 动态渲染签名契约 (Dynamic Signatures & Modal IDs)

由各 render 函数或 `main.ts` 动态注入 `innerHTML` 的交互契约：

| 签名 / 选择器 | 触发函数 | 所在区域 | 职责说明 | 对照结论与改动要求 |
|---|---|---|---|---|
| `#btnSaveBonds` | `renderBonds()` | `#bonds` 内 | 显式点击保存羁绊与卡组策略 | **已有且一致**。两端模板均包含 |
| `#subscriptionKey`| `openSubscriptionModal()` | `#modalSheet` 内 | 卡密激活输入框 | **已有且一致**。两端模板均包含 |
| `[data-stem]` | `openBossModal()` | `#modalSheet` 内 | 传家宝 / Boss 候选卡片点击 | **已有且一致**。两端模板均包含 |
| `[data-apply-rep]`| `openPrestigeModal()` | `#modalSheet` 内 | 声望点数分配确认按钮 | **已有且一致**。两端模板均包含 |
| `[data-close]` | 模态弹窗通用 | `#modalSheet` 内 | 弹窗取消/关闭通用标记 | **已有且一致**。两端模板均包含 |
| `[data-activate-subscription]` | `openSubscriptionModal()` | `#modalSheet` 内 | 卡密激活提交按钮 | **已有且一致**。两端模板均包含 |
| `#hitchPrimarySearch` | `openHitchSearchModal()` | `#modalSheet` 内 | 主搜关键词输入框 | **由 `main.ts` 动态生成并挂载** |
| `#hitchSecondarySearch` | `openHitchSearchModal()` | `#modalSheet` 内 | 副搜关键词输入框 | **由 `main.ts` 动态生成并挂载** |
| `[data-apply-hitch-search]` | `openHitchSearchModal()` | `#modalSheet` 内 | 保存搜房词按钮 | **由 `main.ts` 动态生成并挂载** |
| `#odRunLog` | `ensureRunLogPanel()` | `#scene-app` 底部 | 8 行运行日志轻量尾窗 | **由 `main.ts` 动态注入** |

---

### 2.4 数据委托属性契约 (`data-*` Selectors)

| 属性选择器 | 宿主元素 | 交互行为 | 绑定的配置字段 |
|---|---|---|---|
| `[data-team-rules]` | `aside.hitch-console` | 点击/变更委托 | `follow` / `hitch` 规则分流 |
| `[data-team-cycle-input]` | `input#followCycle` 等 | 局数输入 | `follow_cycle_num` / `hitch_cycle_num` |
| `[data-team-cycle-step]` | `button` | 步进加减局数 | 经 `setCycle()` 写入 |
| `[data-team-rule]` | `button/select` | 单选跟车/蹭车分支 | `follow_after_room` / `hitch_after_goal` |
| `[data-team-pair]` | `input#followPairCode` | 配对码输入 | `follow_pair_code`（≤24 字符） |
| `[data-adv-move]` | `button` | 高级卡组上下调序 | `cards` 阵列重排并落盘 |
| `[data-adv-pick]` | `button` | 高级卡组选用切换 | `cards` 阵列过滤并落盘 |
| `[data-route]` | `select` | 技能进化路线下拉 | `skill_custom_routes` |

---

### 2.5 抽屉开关契约 (`SWITCHES`)

`main.ts` 中的 `SWITCHES` 映射表定义了 DOM 元素、前端 `state` 键与后端 `SettingsDTO` 字段的严格对应关系：

| DOM 元素 ID | 前端 `state` 键 | 后端 `SettingsDTO` 字段 | 类型 | 正式线基线 | 桌面新看板 |
|---|---|---|---|---|---|
| `swSecret` | `autoSecret` | `auto_secret_realm` | `boolean` | `true` | `true` |
| `swCloseML` | `closeMainline` | `auto_close_main_line` | `boolean` | `true` | `true` |
| `swAutoArch` | `autoArch` | `auto_archaeology` | `boolean` | `true` | `true` |
| `swNewRoom` | `newRoom` | `new_room_every_times` | `boolean` | `false` | `false` |
| `swDragon` | `dragonPrefer` | `find_longzhu_where_multi_game` | `boolean` | `false` | `false` |

---

## 3. 逐项差异深度对比与移植改造点

### 3.1 核心冲突：`btnStart` 元素形态与运行控制

- **基线现状**：`prod_html` 中 `#btnStart` 为 `<button type="button" class="primary" id="btnStart">`。
  `main.ts` 直接控制其 `.disabled` 属性并覆盖 `.textContent`（“开始运行” / “不可启动” / “停止中…” / “停止运行”）。
- **新看板设计**：
  ```html
  <input class="run-ctrl" type="checkbox" id="ctrl-running" aria-label="开始或停止运行">
  <label class="primary" id="btnStart" for="ctrl-running" data-od-id="btn-start">
    <span class="ph ico-run">...</span>
    <span class="ph ico-stop">...</span>
    <span id="btnStartTextRun">开始运行</span>
    <span id="btnStartTextStop">停止运行</span>
  </label>
  ```
- **冲突与风险**：
  1. `<label>` 元素原生没有 `.disabled` 属性，`main.ts` 中的 `button.disabled = ...` 无效；
  2. `main.ts` 中的 `btnStart.textContent = ...` 会直接冲掉内嵌的图标与双状态文本 span；
  3. 点击 `<label>` 会触发展开的 `#ctrl-running` 的 `change` 事件，新看板原代码在 `change` 回调里直接调用了内部的 `setRunning()` 与 `fetch('/api/run/start')`，产生重复/绕过行为。
- **改动要求**：
  在移植阶段，必须改造新看板运行控制链路：
  - 点击按钮仅发出意图，禁止直接在前端设置 `running=true`；
  - 必须由 `main.ts` 的 `btnStart` 监听器调度 `flushConfigQueue()` → `validate_preflight` → `start_run` / `stop_run`；
  - 界面运行态（HUD 展开、按钮变红、禁用其他切换等）**完全由 `run_status_changed` 信号驱动**。

### 3.2 阻断项：跟车配对码 `followPairForm` / `followPairCode` 缺失

- **冲突现象**：新看板的 `followBody` 去掉了配对码输入卡片。
- **后果**：`main.ts` 第 754 行执行 `$("followPairForm").addEventListener("submit", ...)` 时直接抛出 `TypeError: Cannot read properties of null`，导致整个前端适配层崩溃终止。
- **改动要求**：
  在移植后新看板的 `followBody` 中恢复 `followPairForm` 与 `followPairCode`（使用新版液态银磨砂卡片样式），保留 `state.teamRules.follow.pairCode`（≤24 字符）的绑定与提交能力。

### 3.3 语义冲突：跟车规则 `follow_after_room` 增加非法枚举 `"end"`

- **现状对比**：
  - 正式线后端契约：`follow_after_room` 仅支持 `{"solo", "arch", "hitch"}`（单刷/考古/蹭车）；
  - 新看板界面：在 `.after-choice` 中增加了一个 `data-value="end"`（“结束”）。
- **后果**：用户若点击“结束”，前端向后端推送 `follow_after_room: "end"`，后端 `Settings.validate_patch` 判定失败并抛错：`"follow_after_room 取值非法"`，配置队列被置为 `BROKEN`。
- **改动要求**：
  去除 `"end"` 按钮，严格保持 `solo`、`hitch`、`arch` 三项，与后端契约完全对齐。

### 3.4 局数语义：`cycle_num` 兜底禁止

- **现状对比**：新看板存在多处 `currentCycle() || 2` 的兜底逻辑。
- **后端契约**：`cycle_num = 0` 表示“不限局数 / 手动停止”，属于极其重要的核心功能。
- **改动要求**：禁止将 0 误判为空并回退为 2，严格支持 0。

---

## 4. HUD 局内悬浮条与 21 阶段进程词对齐规范

`mediator.py` 拥有 21 个标准 `Phase` 枚举。新看板必须完整覆盖，未知状态统一兜底为“运行中”，**严禁将英文枚举直接暴露在 HUD 上**。

| # | 后端 Phase 枚举 | HUD 主文案 (`spoken.say`) | HUD 副文案 (`spoken.extra`) | 芯片短词 (`spoken.chip`) | 动效图标 |
|---|---|---|---|---|---|
| 1 | `BOOT` | 整装待发中 | 点击「开始运行」立即出征 | 待命 | `notch` (旋转) |
| 2 | `WAIT_EXIT` | 正在脱离战场 | 从容返回大厅营地，准备再战 | 返回中 | `flagc` |
| 3 | `LOBBY_ROOM` | 身处游戏大厅 | 正在检索下一个目标车队 | 大厅中 | `search` |
| 4 | `PREPARE` | 秒点准备就绪 | 全员就绪，等待吹响号角 | 已准备 | `door` |
| 5 | `WAIT_UI` | 等待战场开启 | 正在捕捉游戏战斗画面 | 等画面 | `notch` (旋转) |
| 6 | `PLATFORM_MAP` | 地图航线规划中 | 正在选定最佳作战关卡 | 选关中 | `search` |
| 7 | `CREATE_ROOM` | 开启专属车队房间 | 配置房间规则，等待队友集结 | 开房中 | `spark` |
| 8 | `ROOM_WAITING` | 大厅招募队员中 | 队员满员立即发车 | 等队员 | `search` |
| 9 | `ROOM_STARTING` | 全员集结，号角吹响 | 载入战场，带领队伍突进 | 出征 | `play` |
| 10 | `STAGE_SELECT` | 选定目标关卡中 | 锁定收益最高的目标战场 | 选关中 | `search` |
| 11 | `STAGE_STARTING`| 号角吹响，关卡开启 | 全军出击，立刻进入战局 | 进局 | `play` |
| 12 | `HERO_SETUP` | 英雄阵营确认中 | 配置英雄模式与难度奖励 | 确认中 | `crown` |
| 13 | `ERROR` | 未探测到游戏视窗 | 请将游戏窗口置于前台再试 | 异常 | `pause` |
| 14 | `MAIN_LINE` | 努力刷怪中 | 自动锁定目标与技能施放 | 刷怪中 | `play` |
| 15 | `EARLY_CHALLENGE`| 越级挑战强敌中 | 直面强敌，拿下额外重赏 | 打挑战 | `spark` |
| 16 | `ANCHOR_BOSS` | 激战首领 Boss 中 | 直击首领弱点，全力破防 | 斩首领 | `crown` |
| 17 | `LONGZHU` | 四方探寻龙珠中 | 集齐上古秘宝，神力加持 | 寻龙珠 | `spark` |
| 18 | `RECOVER_FAILURE`| 战局异常处置中 | 正在安全处理异常并重整队伍 | 恢复中 | `notch` (旋转) |
| 19 | `QUIT` | 战利品清点完毕 | 从容退场，迎接全新挑战 | 结算完 | `flagc` |
| 20 | `NEXT` | 整顿装备开下一局 | 状态拉满，马上继续刷本 | 下一局 | `play` |
| 21 | `COMPLETE` | 达成既定作战目标 | 计划完成，已安全停止脚本 | 已完成 | `flagc` |
| — | *未知兜底* | **运行中** | 正在执行预设脚本逻辑 | 运行中 | `play` |

> ⚠️ **注意**：`SECRET`、`POST`、`LOBBY_SCAN`、`ROOM_FOUND`、`JOIN`、`SWITCH`、`SKILL_FIND`、`BOND_FIND` 并非后端真实枚举，只能在离线 Mock 演示中作为子环节轮播，不得伪装成真实后端状态。

---

## 5. 自动化契约测试防线 (`tests/kanban_contract.spec.ts`)

为防止后续看板迭代或重构发生接口回归，正式线新增了完整的自动化契约测试：
- **位置**：`ui-v2/tests/kanban_contract.spec.ts`
- **运行命令**：
  ```powershell
  cd G:\刷刷宝\Worktrees\ui-kanban-port-20260912\ui-v2
  npm test
  ```
- **断言覆盖**：
  1. 断言静态 DOM ID 全量存在（32 个核心节点）；
  2. 断言模板中包含所有动态注入标记与选择器（`btnSaveBonds`、`subscriptionKey` 等）；
  3. 断言 `SWITCHES` 全部映射有效；
  4. 断言所有 `data-*` 事件委托属性在 HTML 节点中存在；
  5. 隔离沙箱（Node.js `vm`）执行内联脚本，断言全部全局函数、常量与 `state` 初始字段；
  6. 诊断工具不仅自检基线，还针对桌面新看板执行差异诊断并输出未对齐清单。

---

## 6. 用户裁决与落地记录 (Decisions & Delivery Status)

在 2026-09-12 的沟通过程中，用户已明确拍板以下事项，并在代码库中全量落地：

1. **跟车配对码确认无须存在（用户正式拍板）**：
   - **裁决**：用户明确指示「跟车本来就没有配对码啊，这个业务是凭空加进来的，我根本没有设计」。
   - **落地**：跟车卡片不添加任何配对码元素；`ui-v2/src/main.ts` 中针对 `followPairForm` 的事件监听增加可选保护（`document.getElementById("followPairForm")?.addEventListener(...)`），彻底消除空指针风险；契约测试集同步移除对 `followPairForm`、`followPairCode` 及 `[data-team-pair]` 的强制必选断言。
2. **`btnStart` 控件采用原生 `<button>` 双状态方案（用户批准 Agent 建议）**：
   - **裁决**：保持 `#btnStart` 为原生 `<button>` 元素，容纳 `#btnStartTextRun`（开始运行/不可启动）与 `#btnStartTextStop`（停止中…/停止运行）两个内部 span，同时保留隐藏的 `#ctrl-running` checkbox 供 CSS 选择器兼容。
   - **落地**：保持原生 `disabled` 属性与事件委托，`main.ts` 中通过 `applyRunStatus` 与 `applyLaunchability` 驱动文案与可用性，完全杜绝了旧桌面副本 label checkbox 无法被原生属性禁用的缺陷。
3. **`follow_after_room` 选项对齐**：
   - **裁决**：移除桌面副本中凭空出现的 `"end"` 按钮，严格对齐后端 `Settings` 允许的 `"solo"` / `"arch"` / `"hitch"` 枚举。
4. **HUD 21 阶段进程词全量覆盖**：
   - **落地**：`HUD_SAY` 完整映射正式线 `Phase` 全部 21 个枚举，未知 phase 统一兜底为通用中文“运行中”，绝不泄漏英文枚举。
5. **模式向导与 `MODE_LABEL` 对齐**：
   - **落地**：严格对齐正式线 `test_web_config_shell.py` 门禁，`MODE_LABEL` 统一为标准全称（`solo:"单人模式", lead:"组队带车模式", follow:"组队跟车模式", hitch:"组队蹭车模式"`），提供 `openWizard` 与 `scene-wizard` 原生向导能力。
6. **离线与开发预览模式解耦**：
   - **落地**：`mockBridge.ts` 升级为具备完整信号派发（`snapshot_changed`、`run_status_changed`、`log_appended`）与阶段轮播的诚实 mock 连接层，完全废弃并清除了 `HOST_MODE` 分支、`fetch('/api/...')` 与前端假激活卡密。
7. **待批准提案：蹭车/跟车 360 宽置顶小窗宿主支持**：
   - 第一阶段已在正式线标准 1080×820 下全绿验收。关于 360 宽小窗宿主支持，后续若需推进，将针对 `web_config_shell.py`、`bridge_contract.py` 与 facade 发起变更提案，保持独立审计。

