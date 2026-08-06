# 原版 1.3.8 行为提取与安全迁移矩阵

> **版本**：1.3.8
> **基线程序集**：`C:\Users\10639\Desktop\🎮 影音游戏\1.3.8\GameScript.exe` (.NET Framework 4.8)
> **符号文件**：`C:\Users\10639\Desktop\🎮 影音游戏\1.3.8\GameScript.pdb`
> **分析性质**：只读静态分析与证据整理（未运行原版 EXE、未修改 1.3.8 目录、未复制原版代码或裸键盘鼠标调用）。

---

## 1. 证据等级与分类规则

为了确保事实严谨性，严禁将“名称/资源存在”误写为“行为已确认”。各证据等级定义如下：

### 1.1 证据等级定义
- **`CONFIRMED`**：仅用于某条**具体事实**被直接来源明确支持。
  - 支持来源限定为：`GameScript.exe.config` 中的 `<setting>` 键值对、PDB 中的具体源文件名与 Symbol 符号、`Images/` 目录中实际存在的图片模板文件、用户在 `fixtures/reborn_wow/README.md` 中提供的明确规则/截图、以及当前 `src/` 代码库中已实装的具体逻辑。
- **`INFERRED`**：由多个侧面线索推断得出。必须在文档中逐项写出推断依据和不确定点。
- **`UNKNOWN`**：静态资料与已有证据无法确认时，必须明确标为 `UNKNOWN`，严禁主观推测或填充默认行为。

### 1.2 四分法描述架构
每个功能域必须严格区分以下四个独立部分，不得混淆：
- **A. 原版直接证据**：`exe.config` 配置键值、PDB 源文件名/Symbol、`Images/` 模板文件或 PDB/二进制字符串线索。
- **B. 用户已确认的当前版本行为**：用户在 `fixtures/reborn_wow/README.md` 或 `manifest.json` 中给出的当前版本业务规则。
- **C. 当前代码/回放实际覆盖**：当前 `src/` 和 `tools/run_replay.py` 实际支持的检测、决策与测试覆盖状态。
- **D. 建议的安全迁移策略**：为保证防呆防爆而设计的工程迁移与安全防护规程。

---

## 2. 原版静态事实与模板库梳理

### 2.1 原版模板库梳理（`Images/` 目录）
原版 `1.3.8/Images` 及其子目录递归包含 **267** 个图片文件，按用途分类如下：

1. **状态锚点与控制模板**（`Images/` 根目录，147 个文件）：
   - `mainIdentifier.png`（大厅/地图主界面识别锚点）
   - `startGameBtn.png`（房间/关卡界面“开始游戏”按钮）
   - `stage.png`, `stage1.png`~`stage4.png`（关卡选择标签与界面标识）
   - `tqtz.png`, `xzcz.png`, `bpoint.png`（局内挑战图标）
   - `continueGame.png`（胜利结算“继续游戏”按钮）
   - `archiveChallenge.png`（存档挑战 NPC/面板标识）
   - `cjbtiaozhan.png`（传家宝挑战 NPC/面板标识）
   - `HeroChallenge.png`（左上角“英雄挑战”图标）
   - `damijing.png`（大秘境 NPC/入口弹窗）
   - `mijingOk.png`（大秘境确认弹窗“是”按钮）
   - `quit.png`（左上角“退出游戏”按钮）
   - `gameDisconnect.png`（断线/网络异常弹窗标识）
   - `retryConnect.png`（断线重连按钮）
   - `pauseGame.png`（赌木暂停标识）
2. **Boss 模板库**（`Images/boss/`，51 个文件）：
   - `01霍格.png` ~ `51奈法利安.png`（时光之穴与常规 Boss 头像模板）
3. **传家宝 Boss 模板库**（`Images/chuanjiaobao/`，17 个文件）：
   - `01暴掠龙.png` ~ `17年兽.png`（传家宝 Boss 头像模板）
4. **技能与卡片模板库**：
   - `Images/skills/`（16 个文件）：`asj`, `asjg`, `assx`, `bsxx`, `byj`, `dcw`, `dz`, `hbj`, `hq`, `jf`, `jq`, `ljf`, `pg`, `sdl`, `tl`, `ys`
   - `Images/cards/`（36 个文件）：`baoji`, `chengzhang`, `dapao`, `dasheng`, `gongshen`, `liemoren`, `liliang`, `mingjie`, `shengming`, `zhanshen`, `zhili`, `zhufu` 等

### 2.2 原版配置文件事实核验
在 `GameScript.exe.config` 的 `<setting>` 节点中，**直接确认**存在且仅存在以下 13 项设置及其初始值：

| 配置项名称 | config 节点中确切初始值 | 证据等级 |
| --- | --- | --- |
| `Stage1` | `"3"` | `CONFIRMED` |
| `Stage2` | `"2"` | `CONFIRMED` |
| `RoomPassword` | `""` | `CONFIRMED` |
| `QueryTimeOut` | `"60"` | `CONFIRMED` |
| `DragonBallCount` | `"7"` | `CONFIRMED` |
| `AutoSecretRealm` | `"False"` | `CONFIRMED` |
| `Skills` | `"jq,pg"` | `CONFIRMED` |
| `CJBBoss` | `""` | `CONFIRMED` |
| `SGZXBoss` | `""` | `CONFIRMED` |
| `GameMode` | `"0"` | `CONFIRMED` |
| `GameTimeOut` | `"15"` | `CONFIRMED` |
| `LicenseTxt` | `""` | `CONFIRMED` |
| `BatFile` | `""` | `CONFIRMED` |

#### 特别澄清：PDB / 二进制字符串线索项
以下字段虽然在 PDB 符号或 EXE 字符串中存在，**但并不在 `GameScript.exe.config` 的 `<setting>` 节点中**。不能写为“已确认的配置默认值”，其默认行为和配置来源均记为 `UNKNOWN` 或 `PDB String Clue`：
- `ArchiveBossTime`, `AutoCloseMainLine`, `CloseMainLineTime`, `NewRoomEveryTimes`, `RoomName`, `Cards`, `AutoCard`, `AutoWeapon`, `DamageIncreaseCard`

---

## 3. 关键概念区分与回放状态真相

### 3.1 资产类型区分
1. **原版运行时局部模板**（`1.3.8/Images/*.png`）：旧版小图裁剪，仅作名称与特征词典参考，**严禁直接作为当前全屏检测的唯一手段**。
2. **本地未跟踪素材库**（`fixtures/reborn_wow/`）：用户提供的当前版本完整全屏截图与规则说明。**当前未被 `src/` 或 `tools/run_replay.py` 消费**。
3. **P0-B 真实回放 Manifest**（`fixtures/manifest.json`）：`run_replay.py` 唯一消费的门禁清单。

### 3.2 当前 P0-B 回放门禁实际状态与素材缺口说明
- **P0-A 安全执行链**：已在 `src/gamescript/` 中实装并通过全部 55 个单元测试。
- **P0-B 回放门禁现状**：运行 `python tools/run_replay.py` 实际结果为：
  ```text
  Summary: Total=17, Passed=14, Failed=0, Required Missing=3, Optional Missing=0
  [ERROR] Replay failed gatekeeper check: Required Missing=3, Failed=0
  exit code = 1
  ```
- **门禁阻塞真正原因与素材澄清**：
  1. **房间等待页 (`missing_room_waiting_page`)** 与 **局内主线运行页 (`missing_in_game_main_line`)**：用户在本地 `fixtures/reborn_wow/` 中**已经提供了相关截图**（`room_waiting_host.png`, `main_line_auto_off.png`, `main_line_auto_on.png`），**不需要用户重复上传**。真实缺口是下一阶段需要将这些已有本地素材转换并注册进根 `fixtures/manifest.json` 供 `run_replay.py` 读取。
  2. **断线弹窗 (`missing_disconnect_modal`)**：这是当前**唯一真正缺少**的当前版本全屏截图。
- **结论**：**P0-B 代码与单测已通过，但端到端 Replay 门禁尚未通过**。局内自动挑战、选卡偏好等虽然已有局部 `Mediator` 识别逻辑，但尚未用全屏素材形成端到端 Replay 验收，也未形成结算—存档挑战—传家宝—大秘境的完整安全状态机。

---

## 4. 原版行为提取与安全迁移矩阵（覆盖 10 大功能域）

### 功能域 1：大厅 / 建房 / 房间等待 / 开始游戏
* **A. 原版直接证据**：
  - PDB 符号：`PrimaryGameJob.cs`, `GameRoom.cs`, `GameSelector.cs`
  - `exe.config` 配置：`GameMode="0"`, `RoomPassword=""`, `QueryTimeOut="60"`
  - PDB 字符串线索：`RoomName`, `NewRoomEveryTimes`（配置默认值 `UNKNOWN`）
  - HTML 说明：0=独狼模式（单人/手动点开始），1=带队模式（队长/自动开始），2=赌木模式，3=邪修秘境
  - 模板：`mainIdentifier.png` (大厅), `startGameBtn.png` (开始游戏)
* **B. 用户已确认的当前版本行为**：
  - 房主等待页场景由 `fixtures/reborn_wow/room/room_waiting_host.png` 给出；开始游戏按钮需点击 `start_game_button`。
* **C. 当前代码/回放实际覆盖**：
  - `src/gamescript/vision/lobby_detector.py` 已实现大厅/建房识别；
  - 静态资源检验 `validate_scenes.py` 通过 (99/99)；
  - 回放测试门禁被 `missing_room_waiting_page` 阻塞（本地已有截图 `room_waiting_host.png`，待接入根 manifest）。
* **D. 建议的安全迁移策略**：
  - 房主模式校验 HWND，确认房间等待页后方可点击 `startGameBtn`；非房主/队员模式静默等待，超时 60s 抛出异常或触发恢复。
* **证据等级**：`CONFIRMED`（直接配置与 PDB/模板）/ `INFERRED`（带队模式建房重试逻辑）

### 功能域 2：选关 / Stage1 / Stage2 / 可见关卡 / 开始主线
* **A. 原版直接证据**：
  - PDB 符号：`SelectStageJob.cs`, `StartMainLineJob.cs`
  - `exe.config` 配置：`Stage1="3"`, `Stage2="2"`, `QueryTimeOut="60"`
  - 模板：`stage.png`, `stage1.png`~`stage4.png`, `startGameBtn.png`
* **B. 用户已确认的当前版本行为**：
  - 选关页分第 1 章（旧世大陆）与第 2 章（熔火之心），行可见性受账号解锁限制，严禁推断未解锁行；必须在点击开始前校验目标行高亮/选中态。
* **C. 当前代码/回放实际覆盖**：
  - `src/gamescript/vision/stage_selector.py` 已实现 `StageId(chapter, index)` 精确比较与选中态校验；
  - 单测包含章节区分、跨章比较与滚动查找测试。
* **D. 建议的安全迁移策略**：
  - 不可假设原版会校验高亮态（原版校验逻辑 `UNKNOWN`）；新工程强制实施“选中目标行 -> 校验高亮选中态 -> 点击开始游戏”三步验证规程。
* **证据等级**：`CONFIRMED`（直接配置与代码实现）/ `UNKNOWN`（原版高亮校验细节）

### 功能域 3：主线运行 / 自动任务 / 金币、木材、经验、宝物挑战
* **A. 原版直接证据**：
  - PDB 符号：`AutoGameJob.cs`, `MainStoryJob.cs`
  - PDB 字符串线索：`AutoCloseMainLine`, `CloseMainLineTime`（配置默认值 `UNKNOWN`）
  - HTML 说明：5-5 波次后可自动清理怪物并关闭主线；一局只触发一次
  - 模板：左下角挑战图标 `tqtz.png`, `xzcz.png`, `bpoint.png` 等
* **B. 用户已确认的当前版本行为**：
  - 左下角金币、木材、经验、宝物挑战卡片通过“悬停 + 右键”开启自动；后置确认必须显示绿色 `自动` 标识；若已为绿色 `自动` 禁止重复右键。
* **C. 当前代码/回放实际覆盖**：
  - `Mediator` 已包含识别挑战卡片自动状态和避免重复右键的局部逻辑（`test_challenge_label_maps_to_icon_click_and_detects_auto`）；但本地素材 `main_line_auto_off.png` / `main_line_auto_on.png` 尚未接入根 manifest 形成端到端回放验收。
* **D. 建议的安全迁移策略**：
  - 识别到 `MAIN_LINE_AUTO_OFF` 后，依次执行悬停+右键；检测到 `MAIN_LINE_AUTO_ON` 立即停止右键动作。
* **证据等级**：`CONFIRMED`（PDB/模板/用户规则）/ `INFERRED`（原版波次检测算法）

### 功能域 4：技能选择 / 卡片选择 / 羁绊 / 宝物 / 黑商
* **A. 原版直接证据**：
  - PDB 符号：`AutoSkillJob.cs`, `AutoCardJob.cs`, `AutoGiftJob.cs`, `AutoWeaponJob.cs`
  - `exe.config` 配置：`Skills="jq,pg"`
  - PDB 字符串线索：`Cards`, `AutoCard`, `AutoWeapon`, `DamageIncreaseCard`（配置默认值 `UNKNOWN`）
  - 模板：`Images/skills/` (16 个), `Images/cards/` (36 个), `woodgift.png`, `treasurechest.png`, `bbx.png`
* **B. 用户已确认的当前版本行为**：
  - 当前用户素材包含三选一技能 (`skill_choice_3.png`)、羁绊 (`bond_choice_3.png`)、宝物 (`treasure_choice_3.png`) 与黑商截条 (`black_merchant_card_strip.png`)。四选一、五选一及全屏黑商仍可作为未来补充证据。
* **C. 当前代码/回放实际覆盖**：
  - `Mediator` 已包含按配置技能偏好寻找奖励项的局部逻辑（`test_reward_choice_prefers_configured_skill_in_center_roi`）；但尚未形成完整的卡牌/技能优先度匹配决策器与回放门禁。
* **D. 建议的安全迁移策略**：
  - 原版不匹配时的退回/刷新逻辑记为 `UNKNOWN`；新工程应采用配置规则树，匹配失败时优先选择默认第一项或防卡死跳过，不盲目刷新。
* **证据等级**：`CONFIRMED`（`Skills`配置与模板存在）/ `UNKNOWN`（原版未匹配时的兜底策略）

### 功能域 5：胜利结算 / 继续游戏
* **A. 原版直接证据**：
  - PDB 符号：`AutoWaitGameOverJob.cs`
  - `exe.config` 配置：`GameTimeOut="15"`（单局超时 15 分钟）
  - 模板：`continueGame.png`, `woodSuccess.png`
* **B. 用户已确认的当前版本行为**：
  - 结算页面识别 `victory_continue.png`，点击“继续游戏”按钮转换至战后 NPC 广场。
* **C. 当前代码/回放实际覆盖**：
  - `fixtures/reborn_wow/manifest.json` 已登记 `victory_continue` 状态；`src/` 尚未将战后流程接入主循环。
* **D. 建议的安全迁移策略**：
  - 检测到结算画面后，左键点击“继续游戏”，校验页面变为 NPC 广场或存档面板；若超时 15 分钟未结算，触发异常报警与安全退出。
* **证据等级**：`CONFIRMED`（直接配置与模板存在）/ `INFERRED`（原版战后超时恢复机制）

### 功能域 6：存档挑战 / 时光之穴 Boss
* **A. 原版直接证据**：
  - PDB 符号：`AutoBossJob.cs`
  - `exe.config` 配置：`SGZXBoss=""`
  - PDB 字符串线索：`ArchiveBossTime`（配置默认值 `UNKNOWN`）
  - 模板：`archiveChallenge.png`, `sgzxBoss.png`, `Images/boss/` (51 个文件)
* **B. 用户已确认的当前版本行为**：
  - 打开存档面板 (`archive_challenge_panel.png`)，点击所有可见且已解锁的卡片；若未配置 Boss，默认选择最后一个可见且启用的 Boss。
* **C. 当前代码/回放实际覆盖**：
  - 仅在 `fixtures/reborn_wow/manifest.json` 中定义了规则 Guard，未在 `src/` 中编写执行代码。
* **D. 建议的安全迁移策略**：
  - 不假设原版默认选最后一个 Boss（原版默认选中逻辑 `INFERRED`）；新工程实施“配置优先 -> 默认最后可见启用项”安全退回链。
* **证据等级**：`CONFIRMED`（`SGZXBoss`配置与模板存在）/ `INFERRED`（未配置 Boss 时的默认选中行为）

### 功能域 7：传家宝挑战 / 传家宝 Boss
* **A. 原版直接证据**：
  - PDB 符号：`AutoBossJob.cs`
  - `exe.config` 配置：`CJBBoss=""`
  - 模板：`cjbtiaozhan.png`, `cjbBoss.png`, `chuanjiaobao.png`, `Images/chuanjiaobao/` (17 个文件)
* **B. 用户已确认的当前版本行为**：
  - 打开传家宝挑战 (`heirloom_challenge_bosses.png`)，选择配置或最后一个可用 Boss。界面中左键开启挑战，右键仅用于查看掉落详情。
* **C. 当前代码/回放实际覆盖**：
  - 仅在 `manifest.json` 中定义了防右键误触挑战 Guard，未在运行逻辑中实装。
* **D. 建议的安全迁移策略**：
  - 严格限制传家宝 Boss 对话框内的鼠标动作：仅向 Boss 卡片发送左键；禁向卡片发送右键以防误开掉落弹窗。
* **证据等级**：`CONFIRMED`（`CJBBoss`配置与模板存在）/ `INFERRED`（默认 Boss 规则与右键保护）

### 功能域 8：英雄挑战 / 大秘境 / 大秘境确认
* **A. 原版直接证据**：
  - PDB 符号：`AutoHeroJob.cs`
  - `exe.config` 配置：`AutoSecretRealm="False"`
  - 模板：`HeroChallenge.png`, `damijing.png`, `mijingOk.png`, `mijingSuccess.png`
* **B. 用户已确认的当前版本行为**：
  - 大秘境开启三前置条件（用户明确规则）：1. 地图所有挑战完成；2. 无存活 Boss；3. 左上角 `英雄挑战` 标识可见。若缺 `英雄挑战` 标识严禁触发大秘境。
* **C. 当前代码/回放实际覆盖**：
  - `fixtures/reborn_wow/manifest.json` 登记了 `great_rift_confirm` 状态；`src/` 尚未实装大秘境前置状态校验。
* **D. 建议的安全迁移策略**：
  - 严格执行用户确认的三前置条件，前置不满足时跳过大秘境；右键 NPC 后必须在弹窗中确认识别到 `mijingOk` 按钮方可点击“是”。
* **证据等级**：`CONFIRMED`（`AutoSecretRealm="False"` 配置与模板存在）/ `INFERRED`（原版前置条件与动作序列）

### 功能域 9：退出游戏 / 断线 / 重试 / 超时
* **A. 原版直接证据**：
  - PDB 符号：`GRetry.cs`, `EnvironmentUtils.cs`, `AutoWaitGameOverJob.cs`
  - `exe.config` 配置：`GameTimeOut="15"`, `QueryTimeOut="60"`
  - HTML 说明：`Shift+F12` 为紧急停止热键，可一键强平/关闭脚本程序
  - 模板：`quit.png`, `gameDisconnect.png`, `retryConnect.png`
* **B. 用户已确认的当前版本行为**：
  - 局内主动退出目标为左上角 `退出游戏` 按钮，严禁作为故障恢复猜点。断线重连需当前版本全屏截图。
* **C. 当前代码/回放实际覆盖**：
  - `src/gamescript/input/emergency_stop.py` 已实现真正可取消的 `Shift+F12` 全局急停；
  - P0-B 回放包含 `quit_game_1616x939` 测试，但回放门禁被 `missing_disconnect_modal` 阻塞（这是当前唯一真正缺少的当前版本全屏截图）。
* **D. 建议的安全迁移策略**：
  - 保留全局 `Shift+F12` 急停；检测到未前台绑定或超时 60s 立即强行停机，不盲目重试。
* **证据等级**：`CONFIRMED`（直接配置、急停实现与模板存在）/ `UNKNOWN`（原版断线重试上限与强平细节）

### 功能域 10：配置项优先级与默认策略
* **A. 原版直接证据**：
  - `GameScript.exe.config` 中 13 项确切配置与初始值（`Stage1=3`, `Stage2=2`, `RoomPassword=""`, `QueryTimeOut=60`, `DragonBallCount=7`, `AutoSecretRealm=False`, `Skills=jq,pg`, `CJBBoss=""`, `SGZXBoss=""`, `GameMode=0`, `GameTimeOut=15`, `LicenseTxt=""`, `BatFile=""`）。
* **B. 用户已确认的当前版本行为**：
  - 未配置 Boss 时退回为当前屏幕最后一个可见启用 Boss；关卡选择必须与账号实际解锁相符。
* **C. 当前代码/回放实际覆盖**：
  - 当前实现 (`Settings._from_dict()`) 会自动过滤/静默忽略未知配置字段；`StageId` 和安全执行链保持安全默认值。严格配置校验（拒绝未知配置字段）为后续安全建议策略，非当前已覆盖能力。
* **D. 建议的安全迁移策略**：
  - 优先级：用户显式配置 > 视觉安全退回 > 终止停机。配置无效或目标未解锁时，必须 Fail-Safe 拒绝动作，严禁盲点击；后续版本应补充未知字段校验。
* **证据等级**：`CONFIRMED`（`exe.config` 键值对存在）/ `INFERRED`（原版内部配置解析与优先级代码）

---

## 5. 当前版本人工补充最小清单

以下清单准确标明当前版本的素材缺口状态：

### 5.1 唯一真正缺少、需要用户补充的当前版本截图
1. **当前版本完整断线确认弹窗全屏截图** (`missing_disconnect_modal`)
   - **状态**：**确实缺少**。
   - **用途**：用于解封 `tools/run_replay.py` 的 P0-B 回放门禁，验证网络断线场景。

### 5.2 本地已有素材、仅需后续接入根 Manifest 的项目（无需用户重复提供）
1. **当前版本房间等待页全屏截图** (`missing_room_waiting_page`)
   - **状态**：**本地已有**（`fixtures/reborn_wow/room/room_waiting_host.png`）。
   - **任务**：下一阶段将其转换并注册进根 `fixtures/manifest.json`，无需用户重复上传。
2. **当前版本局内主线运行页全屏截图** (`missing_in_game_main_line`)
   - **状态**：**本地已有**（`fixtures/reborn_wow/main_line/main_line_auto_off.png` 与 `main_line_auto_on.png`）。
   - **任务**：下一阶段将其转换并注册进根 `fixtures/manifest.json`，无需用户重复上传。

### 5.3 未来扩展可选补充证据
1. **当前版本完整黑商状态全屏截图**
   - **用途**：替换仅 350x88 局部裁剪的 `black_merchant_card_strip.png`，建立完整黑市识别与防误触边界。
2. **四选一与五选一技能选择界面全屏截图**
   - **用途**：补充 `skill_choice_3.png` 之外的高阶技能选择布局，适配选卡坐标计算。
3. **当前账号实际要刷的目标关卡视图全屏截图**
   - **用途**：如配置 `4-2` 或 `5-10`，需提供对应章节翻页及目标关卡行高亮的真实截图。

---

## 6. 结论与后续推进路线

1. 原版 1.3.8 的静态资源与配置文件提供了丰富的状态与特征参考，但必须严格区分直接事实（`CONFIRMED`）与推断/未确认项（`INFERRED`/`UNKNOWN`）。
2. 当前新工程 `GameScript-Local` 已完成 P0-A 安全执行链与 55 个单元测试；P0-B 端到端回放门禁目前处于 `Required Missing=3` 的已知阻塞状态（其中 2 个所需素材在 `fixtures/reborn_wow/` 中已有，待接入根 manifest）。
3. 后续功能推进严格遵循：**原版行为提炼 → 当前 UI 截图验证 → 安全迁移 → 回送 Replay 验收** 闭环。
