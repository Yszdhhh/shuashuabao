# 控制中心 + 桌面英雄 + 图鉴库 · 对抗终稿（2026-08-14）

> 只动**外壳层**的产品/安全/工程规格。不实现真机点击，不改 `mediator` 决策。  
> 可视化方案页：Cursor Canvas `control-center-pet-atlas-plan.canvas.tsx`（可在对话旁打开）。  
> 过期文档：`docs/HANDOFF_FRONTEND_CONTROL_PANEL.md` 仍写「Web 面板 / 不做带队」——**以本文为准**。

---

## 0. 一句话

首页只跑已经验证的**单人刷图**；跟车 / 赌木 / 站团本把设置摊开但**启动键物理禁用**；实验室继续走 CLI 且与看板互斥；启动后控制中心进托盘，桌面上只留**点击穿透、不抢焦点**的原创像素英雄；阶段与进度只读 `RuntimeStatus`，禁止 stdout 抠 phase、禁止伪造全局百分比；图鉴是现有 JSON 的只读投影，不是第四份卡名表。

---

## 1. 只读审查：现在到底有什么

### 1.1 桌面单体 `desktop_app.py`（1219 行）

| 事实 | 证据 |
|---|---|
| 窗口默认 **480×420**，首页一条竖列：关卡 +「模式」下拉（实际是普通/英雄）+ 学习模式 + 秘境 + 开始 | `_build_ui` |
| **没有**系统托盘、**没有**宠物窗、**没有**运行方式导航 | 全文无 `QSystemTrayIcon` / `Qt.Tool` |
| 技能网格最多 4 个短码；羁绊网格最多 6 个短码；特殊宝物默认全不放行、分区收起 | `SkillCardGrid` / `BondCardGrid` / `NegativeTreasureGroup` |
| 用户配置写回 **仓库** `ROOT/config/default_settings.json`，不是 `%LOCALAPPDATA%` | `_save_settings_now` / `toggle_run` / `closeEvent` |
| 日志进 `%LOCALAPPDATA%/ShuaBao/logs`；trace 进 APP_DATA；单实例 `QLockFile(APP_DATA/ShuaBao.lock)` | `APP_DATA`、`main()` |
| 阶段来自 **劫持 `print`**：`text.split("phase ")[1].split()[0]` | `MediatorWorker.hook_print` |
| `collect_settings_from_ui` **就地 mutate** `self.settings` 再交给 worker | `settings = self.settings` |

测试 `tests/test_desktop_app.py` 把上述首页契约钉死：没有「认证/官方 Settings/高级设置」字样；技能满 4 张自动折叠；无实机说明必须写「待补」；负面宝物与 `choice_policy` 同源。P0 改 IA 必须改这些测试，禁止改快照糊弄。

### 1.2 print hook 为什么会读到 OLD phase

`Mediator.set_phase` 真实日志是：

```text
[med] phase MAIN_LINE → QUIT note
```

hook 取 `"phase "` 之后的**第一个空白分词**，得到 `MAIN_LINE`（旧值）。`split("→")[-1]` 救不了，因为箭头在第二个 token。  
对照：`api_server.get_run_status` 在 mediator 存活时读 `runner.mediator.phase.name`（这条是对的），但同一文件的 print hook 与 `PHASE_NAME_MAP` 仍会把桌面/旧前端带偏。

`PHASE_NAME_MAP` 缺：`HERO_SETUP`、`RECOVER_FAILURE`、`COMPLETE`（`Phase` 枚举里这三项是存在的）。宠物若继续用这张残表，英雄弹窗和「局数到了安全停」都会显示成英文枚举名或错阶段。

### 1.3 Catalog：缺的是图鉴 UX，不是再造数据模型

| 源 | 规模 | 角色 | 缺口 |
|---|---|---|---|
| `config/skill_card_catalog.json` | **220** 张 / 16 系 | 升级卡效果、前置、互斥、`never_pick` | 无图标；不是运行白名单 |
| `config/skill_meta.json` + `skill_labels.json` | **16** 主技能 | 看板短码、悬停、流派预设 | 16 里 **14** 条 `description` 空（只有爆炎箭、天雷有实机原文） |
| `assets/Images/skills/*.png` | **16** | 找图 + 看板图标 | 升级卡 220 张没有对应 PNG |
| `config/bond_stack_catalog.json` | **65** 条 `need` | 合成张数 + 证据 | 40 条没有 fetter 短码 |
| `config/fetter_labels.json` + `assets/Images/cards/*.png` | **36** | 运行白名单短码 + 字模 | 11 个短码不在 stack catalog（大圣/奇迹/鼓手…） |
| `config/choice_lexicon.json` | **296**（skill 140 / bond 102 / treasure 54） | OCR 别名 | **没有** `kind=merchant` |
| `config/choice_policy.json` | 负面 6 + EX 必拿 4 | 运行策略 | 与 lexicon 宝物 54 条未做图鉴投影 |
| `fixtures/treasure_must_take/` | 4 张实机静帧 | EX 证据 | 可进图鉴「实机」标签 |
| `fixtures/ur_attr_routes/` | 9 张散件静帧 | 三系 UR | 可进羁绊图鉴，不是独立白名单 |
| `official_strategy_defaults.json` | 三线 / 四轮优先级 | 实验室与默认构筑 | 不要复制进图鉴 JSON |

**结论：** 知识已经够做只读图鉴。缺的是 **AtlasView 投影 + 浏览 UX + 证据标签 + 与运行白名单的单向出口**。禁止再手写一份 `atlas.json` 卡名表。

### 1.4 黑商：代码有探测，图鉴没有货品表

- L1 周期含 `merchant`；`_black_merchant_present` 是 **1600×900 右下 HSV 绿块**，不是 OCR 货名。
- 已知安全购买模板：`merchant_wood` / `woodgift`；刷新键 `black_merchant_refresh`。
- 夹具只有 `fixtures/replay/black_merchant_card_strip.png`（局部裁条）。素材缺口文档仍写：**黑市全屏 BLOCKED**。
- `Settings.auto_gambling_time` 注释写明未接入状态机；实验室 `preset=merchant` **并不是黑商模式**，只是 `skill,bond,treasure,reenter`。
- `choice_lexicon` 零条 merchant。图鉴黑商页第一版必须是 **空态 + 待补清单**，不得编货品。

### 1.5 实验室 CLI 已存在

`tools/lab_run.py` 不改 `default_settings.json`。第一版看板**不要提供实验室启动键**，也不要和 CLI 同时 LIVE。

---

## 2. 三角色对抗（必须写进终稿的找茬）

三位角色先独立找茬，再互相打对方的补丁。下面「终稿」已经吸收对抗结果；被否决的补丁见 §10。

### 2.1 Product：10 秒启动 vs 点错进房

**找茬**

1. 前序「820×620 + 左五模式 + 右设置 + 底摘要」把**开始按钮推到第二屏**。当前能 10 秒跑起来，靠的是 480 宽、开始键在首屏。抄竞品尺寸会把主路径毁掉。
2. 左栏五个「模式」和关卡里的「普通/英雄」共用「模式」一词——这就是今天 `cmb_mode` 已经在犯的错。用户会把「跟车」当成一种难度。
3. 图鉴若做成可勾选网格，用户会以为「浏览 220 张升级卡 = 本局会点它们」。运行白名单其实只有 **16 系里最多 4 个** + **羁绊短码最多 6 个**。两套 UI 叠在首页，10 秒启动失败。
4. 宠物若要求点击互动（暂停/喂食/打开看板），用户会去点桌面英雄；点穿失败时点到游戏里。
5. `cycle_num` 今天根本不在面板上。没有局数上限时，「进度」只能显示已完成局数，不能画满条。
6. 实验室和看板同一套大窗口，用户会一边 CLI 采卡一边点「开始运行」——双输入。

**对 Safety / Engineer 的反驳**

- Safety 若要求启动前弹三层确认，10 秒路径死。终稿只保留：**非学习模式一次真机确认 + 未验证运行方式零弹窗直接拒绝**。
- Engineer 若把 220 张卡和 65 条羁绊全铺进首页「完整设置」，Product 否决。完整设置属于图鉴/高级，不属于启动主路径。

**Product 终稿要求**

- 左栏叫 **运行方式**，不叫模式。普通/英雄叫 **关卡难度**。
- **底栏钉死**：摘要 + 预检灯 + 开始/停止。滚动区再长也不许把开始键卷走。
- 默认打开「单人刷图」；跟车/赌木/站团本可见但主按钮禁用，文案是「待验证 · 不可启动」，不要藏起来让用户以为软件没做。
- 图鉴、高级、实验室说明降级为次级页。首页只留：关卡、难度、局数（0=直到手动停）、学习模式、技能折叠、羁绊折叠、开始。
- 运行中禁止切运行方式；难度/关卡在运行中只读。
- 宠物不可点。停止只走托盘 / 控制中心还原 / `Shift+F12`。

### 2.2 Safety（对照 AGENTS.md）

**找茬**

1. **点击穿透失败仍显示置顶窗** = 遮游戏 + 误点防护把脚本停掉，或用户点到英雄却点进游戏。这是比「没有宠物」更坏的结果。
2. 托盘「开始」若复用「上次运行方式」且上次是跟车，等于绕过 UI 门禁。`live_enabled` 必须在 **RunnerService.start 唯一入口**检查，UI 按钮、托盘、热键、API 都走它。
3. 图鉴卡面若是 `QPushButton` 可勾选，浏览即写入 `settings.skills/cards`，autosave 800ms 再写进正在跑的 `Settings` 对象（今天已经是同一引用）。运行中改白名单会乱点。
4. 跟车设置里若出现「快速加入/快速匹配」或颜色兜底，直接打穿 **C4**（`room_start` / `map_create_room` 的 `fallback` 必须恒 `null`）。竞品跟车最容易诱使加这条旁路。
5. 看板与 `lab_run` 各持一份 Mediator = 两套真实点击。现有 `QLockFile` 只管桌面进程，不管 CLI。
6. 配置写安装目录：打包后可能无写权限，失败被 `except: pass` 吞掉；开发时则污染 git 里的 `default_settings.json`。
7. 关闭窗口 `worker.terminate()`（3s 后）：可能在 SendInput 中途杀掉线程。

**对 Product 的反驳**

- 「把跟车设置做完整让用户先填」可以，但 **Start 必须 `setEnabled(False)` + 代码门禁**，不能只靠灰色样式。Qt 快捷键/托盘可以点到禁用按钮背后的 slot。
- 不要为了 10 秒启动默认勾「英雄」。英雄是另一条 L0 链（阵营/难度/局内标识）。默认普通。

**Safety 终稿要求**

- 宠物显示前必须用 `WindowFromPoint` 自检：点在精灵中心应落到**游戏或桌面，而不是宠物 HWND**。失败则永不显示宠物，只留托盘。
- 宠物与游戏客户区相交 → **自动藏宠物、留托盘**（命中测试）。不要「半透明但可点」。
- `ModeSpec.live_enabled=False` 的运行方式：主按钮禁用、托盘无该项、RunnerService 抛 `ModeNotEnabled`。
- 图鉴默认只读。运行中禁止「应用到白名单」。空闲时的应用要二次确认，且只改 **16 系 / 羁绊短码 / 负面宝物放行**，绝不让升级卡名进入 `settings.skills`。
- 跟车证据未齐之前，ModeSpec 的 `forbidden_actions` 写死 `quick_join`、`color_fallback`。C4 测试保持。
- 桌面与实验室共享 `APP_DATA/ShuaBao.live.lock`。
- 用户设置只写 `%LOCALAPPDATA%/ShuaBao/user_settings.json`。仓库 `default_settings.json` 只当出厂默认。
- 关闭：`stop()` + 等待；禁止 `terminate()` 作为常规路径。

### 2.3 Engineer

**找茬**

1. 拆到 `src/gamescript/ui/` 会和现有 **`src/gamescript/ui/uia/`（Windows UI Automation）** 撞名。下一个 agent 会把 Qt 壳和辅助功能后端搅在一起。
2. 前序「拆 5～8 个文件」容易变成空壳目录。Karpathy：P0 只抽出 **ModeSpec + RunnerService + RuntimeStatus + MainWindow**；宠物/图鉴 P1/P2 再长文件。
3. `Settings` 就地 mutate + 运行中 autosave = worker 与 UI 抢同一 dataclass。必须在 start 时 **深拷贝快照** 交给 Mediator。
4. print hook 即使改成取箭头右侧，仍会被 `[med] unhandled phase`、`phase=`、`decision context=... phase=` 多种格式打穿。**不要修正则，删掉相位解析。**
5. `PHASE_NAME_MAP` 与 `Phase` 枚举会再漂移。标签表必须与 `Phase` 同文件或由枚举生成，并单测「每个 Phase 都有中文」。
6. 进度条若用 `phase_index / len(Phase)`，建房和主线会被画成 40% 和 70%——用户已否决。进度是 **有界量测**，不是状态机下标。
7. 现有测试从 `desktop_app` import `MainWindow`。P0 必须 **再导出**，否则外壳重构把全量 pytest 打红。
8. `collect_settings_from_ui` 把 `1-10` 写成 `stage1=10, stage2=10` 是既有quirk，外壳拆分时**不要顺手改**，那是 L0 语义，会搅进跨层提交。

**对 Product / Safety 的反驳**

- 「控制中心 820×620」不是工程约束。Qt 最小尺寸按底栏 + 左栏计算即可；硬编码品牌尺寸没有回归价值。
- 不要为宠物引入新原生依赖（透明窗用 Win32 API + 现有 PySide6 足够）。
- 不要在 P0 做精灵图动画；没有用户像素稿就用纯色占位也会被当成产品完成——P0 **不显示宠物**。

**Engineer 终稿要求**

- 新包名：`src/gamescript/shell/`。`desktop_app.py` 只留 `main()`、锁、再导出。
- `RuntimeStatus` 为 frozen dataclass；worker 定时（200ms）从 `mediator` 抽快照，`Signal` 传到 GUI。print 只做日志。
- `RunnerService.start(mode_id, settings_snapshot)` 是唯一 LIVE 入口。
- 用户设置与出厂默认分离。
- 一层提交：本计划落地时 **只动外壳 + 对应测试 + 本文档**，不碰 mediator / scenes.json / choice_policy 判定。

### 2.4 三角色互相打补丁后的收敛

| 冲突 | 谁赢 | 终稿 |
|---|---|---|
| 窗口要大而全 vs 10 秒启动 | Product | 底栏钉死；默认 720×560；图鉴另页 |
| 跟车要展示 vs 不能误启 | 两者 | 展示完整设置 + `live_enabled=False` 硬门禁 |
| 宠物要可爱可点 vs 点击穿透 | Safety | 宠物不可点；交互全在托盘 |
| 图鉴要能勾选 vs 白名单漂移 | Engineer + Safety | 只读浏览；空闲时单向「应用到本局」 |
| 拆到 `ui/` vs 已有 `ui/uia` | Engineer | 拆到 `shell/` |
| P0 就上宠物 vs 穿透未验证 | Safety + Engineer | P0 无宠物；P1 穿透自检失败则永不显示 |
| 修 print 正则 vs 结构化状态 | 全员 | 删除相位解析 |

---

## 3. 外部审查

### 3.1 刷刷护肝宝57（静态拆解，2026-08-13）

**学**

- **运行方式隔离**：五个 qmc，不是一个巨型 if。我们用 `ModeSpec` + 同一个 Mediator，不复制五份核心。
- **公共外壳生命周期**：开始/停止/保存/说明在壳上，不在每个脚本里。
- **首页先选运行方式，再出该方式的字段**；风险提示贴在字段旁。
- **单入口交付**（用户只看见一个快捷方式）。内部本来就可以有 OCR sidecar。

**不学**

- 固定 1920×1080、100% 缩放、禁止碰鼠标、用户保证环境正确。
- 不透明加密宏、无效 Authenticode、管理员+高熵壳当信任。
- Win10/Win11 当「运行方式」——那是兼容档，不是玩法。
- 跟车/赌木/站团本「有按钮就做」。没有入口帧、完成条件、失败分支、动作白名单、预算之前，只展示不可启动。
- 颜色找「快速加入」。C4。

### 3.2 Codex / Petdex 一类桌面宠物

社区常见形态：`pet.json` + 一张 spritesheet；状态行 `idle / running / waiting / failed / review`。

**学**

- **清单驱动动画**：状态名 → 帧区间，而不是每个 Phase 一张图。
- **一张 spritesheet**，不要 50 个 PNG 文件。
- 状态很少（≤10）。把 19 个 `Phase` 直接做成 19 套动画是浪费，而且缺素材。
- `waiting` 与 `failed` 分开：等锚点 ≠ Fail-Closed。

**不学**

- **review 可点击**（等人审 diff）。我们的宠物必须点击穿透；「等人」对应 Fail-Closed / 托盘气泡，不是点英雄。
- 宠物当主 UI（喂养、拖拽、点头切换模式）。
- 用原作角色（阿尔萨斯/伊利丹等）或游戏内立绘当桌面英雄。用户已拍板：**原创像素、经典魔兽氛围、不是原作角色**。
- 用宠物进度条表示「agent 完成百分比」。那是另一种伪造。

---

## 4. 交互主路径（逐步）

目标：已保存过设置的用户，打开 → 看摘要 → 预检绿 → 开始，**10 秒内**进入 LIVE（含一次真机确认）。

```text
[空闲] 控制中心可见
  1. 运行方式默认「单人刷图」（live_enabled=true）
  2. 读 user_settings.json；没有则出厂 default_settings
  3. 用户改：关卡、关卡难度、局数、（可选）展开技能/羁绊
  4. 底栏摘要实时刷新（只读拼接，不写盘直到防抖）
  5. 预检（只读，零输入）
        管理员完整性 / 单实例 live.lock / 实验室未在跑
        目标窗口标题可枚举（找不到=黄灯，不阻止学习模式）
        模板清单存在 / OCR sidecar 若 live 则探活
        ModeSpec.live_enabled
  6. 点「开始运行」
        学习模式：无管理员要求，直接 start
        真机：一次确认框（默认 No）→ RunnerService.start
        未验证运行方式：按钮 disabled；若被调用 → 拒绝且记日志
  7. start 成功
        深拷贝 Settings 给 worker
        控制中心 hide → 托盘
        P1+：宠物 show（仅当穿透自检通过且不遮游戏客户区）
  8. 运行中
        底栏（若用户从托盘「打开控制中心」）只读 + 停止
        运行方式列表 disabled
        图鉴可浏览，不可应用到白名单
        进度按 §8，禁止全局百分比
  9. 停止 / Fail-Closed / COMPLETE
        宠物切 failed 或 complete，3s 后可回到 idle
        控制中心还原；live.lock 释放
        Fail-Closed：托盘气泡 + 打开 incident 目录的入口，不自动再点
```

紧急停止：已有 `Shift+F12` / `StopSignal`。宠物不接管热键。

---

## 5. 每个运行方式卡片：显示什么、禁用什么

左栏是卡片列表，不是假按钮。右栏只渲染当前 `ModeSpec.settings_schema`。

| id | 左栏徽章 | 右栏显示 | 右栏禁用 / 不显示 | 主按钮 |
|---|---|---|---|---|
| `solo_farm` | 可启动 | 关卡 `N-M`；**关卡难度** 普通/英雄；英雄才显示阵营+1–5 级（默认肯瑞托，未验证阵营黄字「L0 门控另算」）；`cycle_num`（0=手动停）；学习模式；秘境；技能折叠（≤4 系）；羁绊折叠（≤6 短码）；特殊宝物折叠 | 房间名/密码；「快速加入」；实验室 `lab_focus` | 启用 |
| `follow_team` | 待验证 | 说明：跟车不建房；字段占位（等待队长/掉线/回房——文案级）；**找房大厅列表**标明「证据由找房专项提供，见 §12.2」 | 所有会触发 InputExecutor 的控件；快速加入 | **不可启动** |
| `gamble_wood` | 待验证 | 章节/关卡；「第 1 个宝物」只读说明（竞品有此字段，我方无完成条件） | 启动；与单人刷图共享的技能网格（避免用户以为会刷） | **不可启动** |
| `raid_wait` | 待验证 | 4–8 小时展示；「先点游戏内兑换魔团本」人工步骤清单 | 启动；任何自动进本点击 | **不可启动** |
| `lab` | CLI | 只读：如何跑 `tools/lab_run.py` / 桌面 bat；preset 列表；**「看板不启动实验室」** | 开始运行；与 LIVE 同时开 | **不可启动**；若检测到 lab 进程则单人刷图也拒绝 |

共用底栏：

- 摘要一行：`单人刷图 · 1-8 · 普通 · 技能奥数箭/激光/射线/剑气 · 学习关`
- 预检灯：绿可启动 / 黄可学习不可真机 / 红拒绝
- 主按钮文案：可启动「开始运行」；未验证「待验证 · 不可启动」；运行中「停止运行」

英雄难度不是运行方式。切换普通/英雄只改 `auto_reputation`，不切 `ModeSpec`。

---

## 6. 看板信息架构

```text
┌─ 720×560（最小约 640×500）─────────────────────────────┐
│ 刷刷宝 Vx.y          空闲 | 已完成 0 局                  │
│ [单人刷图] [跟车] [赌木] [站团本]     次级：图鉴 高级     │
├────────────┬──────────────────────────────────────────┤
│ 运行方式   │  仅当前方式的设置（可滚动）                  │
│  · 单人    │                                          │
│  · 跟车    │                                          │
│  · 赌木    │                                          │
│  · 站团本  │                                          │
│            │                                          │
├────────────┴──────────────────────────────────────────┤
│ 摘要 …     预检 ●      [开始运行]                       │  ← 钉死
└──────────────────────────────────────────────────────┘
```

**降级**

- **图鉴**：次级页，P2 才做。P0 可以有入口但显示「P2」。
- **高级**：分辨率提示、OCR 模式只读、日志折叠、打开日志目录。不要把 mediator 的 40 个字段摊开。
- **实验室**：不是左栏可启动项；放高级里的说明，或左栏第五项永远禁用。

**运行中**

- 左栏 `setEnabled(False)`。
- 从托盘「打开控制中心」允许查看只读设置与日志，不允许改 `ModeSpec`。
- 停止后才解锁。

**实验室互斥**

- P0 看板不启动 lab。
- `lab_run` 与看板抢 `ShuaBao.live.lock`；谁先拿到谁跑，另一边明确报错。

不要把控制中心和实验室做成「两个可同时 LIVE 的入口」。

---

## 7. 图鉴库（可落地）

### 7.1 数据 vs UX

缺的是 **UX + 投影层**。不要新的权威卡名表。

```text
AtlasView（运行时 join，可缓存）
  规范名/别名     ← choice_lexicon.json          【OCR 唯一】
  技能树效果/前置  ← skill_card_catalog.json      【升级卡唯一】
  主技能标签/预设  ← skill_meta.json + skill_labels.json
  羁绊张数/证据    ← bond_stack_catalog.json      【张数唯一】
  运行短码         ← fetter_labels.json（仅短码↔中文）
  负面/必拿旗标    ← choice_policy.json           【策略唯一】
  图标             ← assets/Images/skills|cards + fixtures 静帧
```

禁止：图鉴页把卡名抄进第三份 JSON；禁止 UI 硬编码负面宝物名单（今天已由测试钉成与 policy 同源，必须保持）。

`fetter_labels` 与 `bond_stack_catalog` 的 40/11 不对称：**图鉴两列都要展示**，分别标「有短码可进白名单」/「仅知识、不能勾到运行」。不要为了图鉴完整去猜短码（会污染 `settings.cards` 找图）。

### 7.2 IA

```text
图鉴
  筛选：全部 / 技能系 / 升级卡 / 羁绊 / 宝物 / 黑商
  搜索：规范名 + lexicon 别名
  来源标签：实机 | 攻略 | 待补
  卡片：名、系/张数、一句话效果、证据、图标或灰块
  详情：前置/互斥/never_pick；不得编数值（空 description 显示待补）
```

来源规则（已有字段，不发明）：

- 实机：`seen`/`source` 含 lab OCR、user 截图、fixtures 路径、`treasure_must_take`、`ur_attr_routes`
- 攻略：`official_strategy_defaults` / 抖音转述且尚未实测（提速、生命、血势、血魔、剑术）
- 待补：`skill_meta.description` 空；黑商货品；无图标

### 7.3 与运行白名单：单向、不重复

| 对象 | 图鉴 | 运行白名单（首页网格） |
|---|---|---|
| 16 主技能系 | 浏览 + 空闲时可「用作本局技能」 | `settings.skills` ≤4；现有 `SkillCardGrid` |
| 220 升级卡 | **只读**。点它们不能写入 skills | 由目录 `prereq/exclude/never_pick` 在策略层生效 |
| 有短码的羁绊 | 浏览 + 空闲「用作本局羁绊」 | `settings.cards` ≤6 |
| 无短码的羁绊 | 只读知识 | 不能勾 |
| EX 宝物 | 只读，标「策略必拿」 | 不在网格里勾；`must_take_names` |
| 负面宝物 | 只读 + 指向首页折叠区 | 仅 `treasure_allow_negative` 逐张 opt-in |
| 黑商 | 空态 | 无白名单 |

首页技能/羁绊网格 **保留**，图鉴不替代它们。图鉴是百科；网格是本局允许点什么。

### 7.4 图标与版权

- **可以**：继续用现有 `skills/*.png`、`cards/*.png` 做**本机工具内**展示（它们已是找图模板）。实机裁卡进 fixtures 作证据缩略图，不对外再分发原作卡面包。
- **不可以**：把魔兽原作角色、竞品壳资源、从网上扒的立绘当桌面英雄或商店图。
- **升级卡 220**：无图标则灰块 + 名称；需要用户从技能树录屏裁切才补，禁止合成伪卡面。
- **桌面英雄**：全新像素，独立版权；与图鉴卡面不是同一套素材。

### 7.5 黑商图鉴缺什么证据

必须用户补（见 §12），否则页上只写：

- 有：右下五卡条探测、买木模板名、刷新键名、局部夹具
- 无：全屏 1600×900、货品规范名、价格/限购、丹药与吞卡关系的图鉴条目、OCR 词典

在证据齐之前，图鉴不得列出「建议购买清单」——那会变成无证据策略。

### 7.6 单一数据源纪律

改名/别名 → 只改 `choice_lexicon`。  
改张数 → 只改 `bond_stack_catalog`。  
改升级效果 → 只改 `skill_card_catalog`。  
改必拿/负面 → 只改 `choice_policy`（测契约）。  
图鉴代码只 join。P2 加一个测试：投影里的技能规范名 ⊆ lexicon ∪ catalog；负面名 = policy。

---

## 8. RuntimeStatus 与进度条契约

### 8.1 快照（worker 线程生产，GUI 只读）

从 mediator **字段**读取，不解析 stdout。建议字段（实现时可同名）：

```text
running: bool
runner_state: IDLE | STARTING | RUNNING | STOPPING | COMPLETE | FAILED
phase: Phase.name
phase_label: 中文（表必须覆盖全部 Phase，含 HERO_SETUP / RECOVER_FAILURE / COMPLETE）
context: str            # 已有 context 缓存
s0_outcome / failure_streak / recovery_kind
game_count: int
cycle_num: int          # 来自 settings 快照，不是 print
round_started_at / round_deadline / round_timeout_s
panel_state
last_error
hwnd_ok: bool
```

GUI 200ms 取最新快照。print hook **只转发日志**。

### 8.2 进度：禁止伪造全局百分比

进度控件只有三种合法形态：

| 形态 | 何时 | 显示 |
|---|---|---|
| **局数比** | `cycle_num > 0` | 确定条 `game_count / cycle_num`，文字「第 n / N 局」 |
| **本局耗时** | `phase == MAIN_LINE` 且已有 round 起点 | 确定条 `elapsed / round_timeout_s`，文字「本局 mm:ss / 硬超时 mm:ss」 |
| **循环读条** | L0：`PLATFORM_MAP` `CREATE_ROOM` `ROOM_*` `STAGE_SELECT` `STAGE_STARTING` `HERO_SETUP`；以及等锚点 | **不定条** + 准确文字，例如「选关 · 等 1-8 出现」「建房 · 等房间锚点」 |
| **无条** | 空闲、COMPLETE、ERROR/Fail-Closed | 只给文字：「空闲」「已达局数，已安全停止」「Fail-Closed · 零输入」 |

禁止：`ordinal(phase)/count(Phase)`、把 BOOT→COMPLETE 映射成 0–100、把不定阶段画成 30%。  
`cycle_num==0` 时**不要**把「已完成 3 局」画成满条。

### 8.3 宠物动画：8–10 个，由 Phase×context×S0 映射

清单建议放 `assets/pet/pet.json`（P1，用户给 spritesheet 后再填帧区间）。状态不得超过 10 个。

| anim | 定量条件（全部满足才进入） | 头顶文案 |
|---|---|---|
| `idle` | 未运行 | 空闲 |
| `boot` | RUNNING 且 phase∈{BOOT, WAIT_UI, WAIT_EXIT} | 预检/等 UI |
| `lobby` | phase∈{LOBBY_ROOM, PREPARE, PLATFORM_MAP, CREATE_ROOM, ROOM_WAITING, ROOM_STARTING} | 用 phase_label，不定条 |
| `stage` | phase∈{STAGE_SELECT, STAGE_STARTING, HERO_SETUP} | 「选关」或「英雄难度」+ 不定条 |
| `run` | phase==MAIN_LINE 且 panel 非三选一等待 | 局数比或本局耗时 |
| `wait_panel` | MAIN_LINE 且 panel_state 表示技能/羁绊/宝物会话未决 | 「等 OCR / 刷新」不定条 |
| `recover` | phase==RECOVER_FAILURE 或 recovery_kind 非空且未失败出局 | 「恢复中」不定条 |
| `quit` | phase∈{QUIT, NEXT} | 「退出本局」 |
| `complete` | phase==COMPLETE 或 runner_state==COMPLETE | 「局数到了 · 已停」 |
| `failed` | phase==ERROR 或 runner_state==FAILED 或 Fail-Closed | 「已停 · 零输入」 |

缺 spritesheet 时：P1 可用静止剪影 + 文案，**仍然要跑穿透自检**。不要用系统进度环冒充血条。

`review`（Petdex）不采用。对人沟通走托盘。

---

## 9. 宠物窗口技术要点

### 9.1 必须满足的行为

运行时宠物 **无焦点、点击穿透**。做不到就**不显示**，只留托盘。否则遮游戏并触发误点防护。

### 9.2 Qt + Win32

创建后、`show()` 前设置：

```text
Qt.Tool
Qt.FramelessWindowHint
Qt.WindowStaysOnTopHint
Qt.WindowDoesNotAcceptFocus
Qt.WindowTransparentForInput      # 若绑定失败视为穿透失败
WA_TranslucentBackground
WA_ShowWithoutActivating
WA_QuitOnClose = False

Win32 GWL_EXSTYLE |=
  WS_EX_LAYERED
  WS_EX_TRANSPARENT               # 命中测试穿透
  WS_EX_NOACTIVATE
  WS_EX_TOOLWINDOW                # 不进任务栏
不要 WS_EX_APPWINDOW
SetWindowPos(..., SWP_NOACTIVATE)
```

不要 `Qt.Dialog` / `Qt.Window` 当宠物。不要 `grab` 键盘。

### 9.3 自检与降级（硬）

1. show 后对精灵中心做 `WindowFromPoint`。若返回宠物 HWND → **立即 hide**，托盘提示「无法点击穿透，已停用桌面英雄」。
2. 250ms 定时：宠物矩形 ∩ 游戏客户区 ≠ ∅ → hide 宠物，留托盘（用户从托盘可「强制显示」，但强制后若仍相交则再次 hide，避免对着游戏开洞）。
3. 目标 HWND 丢失：hide 宠物，状态 `failed` 文案走托盘。
4. 任何降级**禁止**改成「不穿透但半透明可点」。

### 9.4 位置与尺寸

- 精灵约 96–128px，头顶文案约 180×48，整体小。
- 默认贴在游戏窗口**外侧**（右或下），不要叠在客户区上。
- 多显示器：只跟随游戏窗口所在屏。
- 不可拖（拖需要命中）。要改位置只能空闲时在高级里选「左/右/下」。

### 9.5 进程与焦点

与控制中心同一进程，避免第二套 Qt 事件循环。控制中心 `hide` 不是 `close`。`QLockFile` 仍是单实例。第二启动应激活已有托盘，不新建 worker。

---

## 10. 对抗后被否决的坏主意

1. **可点击宠物（暂停/喂养/打开看板）** — 与穿透互斥；失败即误点游戏。  
2. **用 phase 下标画 0–100% 总进度** — 用户已否决伪造全局百分比。  
3. **修 print 正则取箭头右侧** — 格式不唯一；结构化字段已存在。  
4. **图鉴网格直接当技能/羁绊白名单** — 220≠4、65≠6；升级卡名写入 `skills` 会让找图与策略崩。  
5. **P0 实现跟车/赌木/站团本点击** — 无证据；C4 风险；跨层。  
6. **实验室和看板同时 LIVE** — 双 Mediator 双输入。  
7. **拆到 `src/gamescript/ui/`** — 与 `ui/uia` 撞名。  
8. **把 `default_settings.json` 继续当用户偏好文件** — 污染仓库/安装目录。  
9. **原作角色当桌面英雄** — 版权；用户已拍板原创像素。  
10. **Electron/WebView 透明宠物** — 多进程、焦点、杀软；现有 PySide6 足够。  
11. **五份 Mediator / 五份 flow 复制** — 学隔离不学复制；本阶段不拆 mediator。  
12. **启动前三连确认框** — 毁 10 秒路径；未验证方式应直接禁用。  
13. **托盘「重复上次」不检查 live_enabled** — 门禁旁路。  
14. **黑商图鉴先编一份货品表** — 无 lexicon、无全屏帧。  
15. **P0 就画宠物占位动画** — 未做穿透自检的置顶窗比没有更危险。  
16. **运行中允许切运行方式** — 点错进房。  
17. **跟车用颜色兜底点快速加入** — C4。  
18. **为图鉴手写 atlas.json 卡名** — 与 lexicon/catalog 三份漂移。  
19. **关闭窗口 terminate 线程** — 可能截断 SendInput。  
20. **控制中心必须 820×620** — 品牌尺寸；底栏钉死比尺寸重要。

---

## 11. 分阶段交付（只动外壳层）

一层一个 commit。禁止顺手改 mediator / scenes / choice_policy 判定。

### P0 — 看板 + ModeSpec 门禁

- `src/gamescript/shell/{mode_catalog,runner_service,runtime_status,main_window}.py`
- `desktop_app.py` 瘦身为入口并再导出，保住 `tests/test_desktop_app.py` 再迁移
- 左：运行方式；右：当前设置；底：摘要+预检+启动
- 用词：运行方式 ≠ 关卡难度
- `live_enabled` 仅 `solo_farm=true`；其余 UI 展示但不可启动
- 用户设置写入 APP_DATA；出厂默认只读
- start 深拷贝 Settings；运行中 UI 不 mutate worker 那份
- 实验室不从看板启动；live.lock 预留（lab_run 接线可同 commit 或紧随，仍算外壳/工具）
- **不**做宠物窗
- 进度：有 `cycle_num` 显示局数比；否则只显示已完成局数数字，不画假条
- 门禁：`pytest tests/test_desktop_app.py` + 现有全量；`release_gate.py`

### P1 — RuntimeStatus + 宠物

- 删除相位 print 解析（桌面与 api_server hook 的 phase 分支）
- `PHASE` 中文表与枚举对齐的单测
- 宠物窗 + 穿透自检 + 遮游戏则藏
- 动画 8–10 态；无稿则剪影+文案
- 托盘：打开控制中心 / 停止 / 退出；**没有**「启动跟车」
- MAIN_LINE 显示本局耗时/硬超时；L0 不定条+文字

### P2 — 图鉴只读

- AtlasView join；搜索；来源标签
- 与网格不重复；运行中不可应用白名单
- 黑商空态页
- 投影一致性测试

### P3 — 未验证运行方式仍不可启动

- 跟车/赌木/站团本 UI 可继续补字段与说明
- **仍然** `live_enabled=false`，直到找房专项交出证据并且另开 L0 层提交
- 本阶段外壳只保证门禁不被「字段变全」带崩

---

## 12. 需要用户补充的素材

### 12.1 外壳直接依赖

| 素材 | 规格 | 用途 | 缺了怎么办 |
|---|---|---|---|
| 桌面英雄 spritesheet | 原创像素；横条或网格；每态 4 帧左右；不要原作角色；经典魔兽氛围（板甲/斗篷/营地火，不要伊利丹） | P1 宠物 | 剪影+文案，仍要穿透 |
| `pet.json` 帧表 | 与 §8.3 十态名字对齐 | 动画 | 工程师可先写空帧 |
| 黑商 **全屏** 1600×900 | 真机，非合成 | 图鉴空态→有图；**不**自动等于策略完成 | 黑商图鉴维持待补 |
| 黑商单卡裁切 + 游戏内名称 | 每张货品一张 | lexicon `kind=merchant` 的未来输入 | 禁止先编名 |
| 14 个主技能卡面原文 | 现仅爆炎箭/天雷有 | 图鉴/悬停 | 继续「说明待补」 |
| 羁绊缺图标的 40 个知识条目 | 实机裁条可选 | 图鉴缩略图 | 灰块+名 |

### 12.2 找房专项接口（另一路 agent，本文不收口）

跟车 `live_enabled` 保持 false，直到下列接口有真机证据（禁止合成帧冒充）：

```text
FollowTeamEvidence（建议目录 fixtures/follow_team/）
  lobby_room_list.png          # 大厅房间列表全屏 1600×900
  lobby_room_row.png           # 单行房间模板
  join_room.png                # 「加入」而非「快速加入/快速匹配」
  room_list_empty.png
  room_password_dialog.png     # 若有
  video: 找房大厅列表操作录像

ModeSpec.follow_team 只消费：
  entry_scene, allowed_actions, forbidden_actions=["quick_join","color_fallback"]
  不得改 room_start / map_create_room 的 fallback=null
```

找房难度、列表滚动、房间过滤由该 agent 负责。外壳只保留卡片和门禁。

2026-08-14：列表录像已落到 `fixtures/lobby_hitch_20260814/`，骨架阶段已按录像改。**仍** `live_enabled=false`，未接点击。详见 `docs/research/MODE_SKELETON_AND_LOBBY_HITCH_20260814.md`。

---

## 13. 测试与回归（外壳）

P0 至少：

- 未验证 `mode_id` 调用 `RunnerService.start` → 不创建 Mediator、零输入
- 托盘菜单不含未验证方式
- `collect` 不再返回与 worker 共享的同一 `Settings` 对象
- 用户设置路径在 APP_DATA（测试用 tmp）
- 首页开始键在未滚动时可见（几何断言或「底栏 widget isVisible」）
- 「关卡难度」文案存在，「运行方式」与普通/英雄不混名
- 保留：负面宝物同源、技能待补不编数值、空技能不拦截

P1 至少：

- 每个 `Phase` 都有中文标签
- 用假日志 `[med] phase MAIN_LINE → QUIT` **不得**把 GUI 阶段写成 MAIN_LINE（回归 print hook 已死）
- `cycle_num=0` 不渲染确定满条
- 穿透自检失败 → `pet_window` 不 show

P2：图鉴投影 ⊆ 权威 JSON；点击图鉴升级卡不改 `settings.skills`。

契约 C2：本计划不新增局内字段。若 P1 只读 mediator 已有属性，不必改 `INGAME_POLLUTION`。若有人把 GUI 状态写进 mediator——拒绝。

---

## 14. 给实现 agent 的边界

做：`shell/`、桌面入口、托盘、宠物窗、图鉴投影、文档。  
不做：mediator 选卡/建房/跟车点击、scenes 颜色兜底、伪造断线帧、原作角色、实验室与看板双开 LIVE。

权威现状仍是 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`。本文只约束外壳方案；真机选关/技能策略以交接文档顶部为准。
