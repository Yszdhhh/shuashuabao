# 原版 1.3.8 行为提取与安全迁移矩阵

> **版本**：1.3.8  
> **基线程序集**：`C:\Users\10639\Desktop\🎮 影音游戏\1.3.8\GameScript.exe` (.NET Framework 4.8)  
> **符号文件**：`C:\Users\10639\Desktop\🎮 影音游戏\1.3.8\GameScript.pdb`  
> **分析性质**：只读静态分析与证据整理（未运行原版 EXE、未修改 1.3.8 目录、未复制原版代码或裸键盘鼠标调用）。

---

## 1. 概述与证据等级说明

本矩阵旨在将原版 1.3.8 的“**状态识别 → 配置项 → 决策 → 动作 → 后置状态/超时处理**”进行全面梳理，为新工程 `GameScript-Local` 提供具备防呆防爆特性的安全迁移依据。

### 证据等级标记定义
- **`CONFIRMED`**：有直接配置项（`GameScript.exe.config`）、C# 类/PDB 符号、原版 HTML 文档或原版 `Images/` 模板文件支持。
- **`INFERRED`**：由多个侧面证据推断，并已在矩阵中写明明确的推断理由。
- **`UNKNOWN`**：无法从原版静态证据确认，严格禁止主观推测或臆造逻辑。

---

## 2. 原版模板库梳理（按用途分类）

原版 1.3.8 的 `Images/` 目录共包含 **251** 个图片文件，按用途分类如下：

### 2.1 状态锚点与控制模板（`Images/` 根目录）
| 模板文件名 | 原版用途描述 | 对应流程节点 | 证据等级 |
| --- | --- | --- | --- |
| `mainIdentifier.png` | 大厅/地图主界面识别锚点 | 大厅识别 | `CONFIRMED` |
| `startGameBtn.png` | 房间/关卡界面“开始游戏”按钮 | 房间等待/选关开始 | `CONFIRMED` |
| `stage.png`, `stage1.png`~`stage4.png` | 关卡选择标签与界面标识 | 选关界面识别 | `CONFIRMED` |
| `tqtz.png`, `xzcz.png`, `bpoint.png` 等 | 局内金币、木材、经验、宝物挑战图标 | 主线自动任务开启 | `CONFIRMED` |
| `continueGame.png` | 局内胜利结算“继续游戏”按钮 | 胜利结算 | `CONFIRMED` |
| `archiveChallenge.png` | 存档挑战 NPC/面板界面标识 | 存档挑战 | `CONFIRMED` |
| `cjbtiaozhan.png` | 传家宝挑战 NPC/面板界面标识 | 传家宝挑战 | `CONFIRMED` |
| `HeroChallenge.png` | 左上角“英雄挑战”图标/开启标识 | 英雄挑战/大秘境前置 | `CONFIRMED` |
| `damijing.png` | 大秘境（大秘境 NPC/入口弹窗） | 大秘境开启 | `CONFIRMED` |
| `mijingOk.png` | 大秘境确认弹窗“是/确定”按钮 | 大秘境确认 | `CONFIRMED` |
| `quit.png` | 左上角“退出游戏”按钮 | 安全退出游戏 | `CONFIRMED` |
| `gameDisconnect.png` | 游戏断线/网络异常弹窗标识 | 断线处理 | `CONFIRMED` |
| `retryConnect.png` | 断线重连/重试按钮 | 重连重试 | `CONFIRMED` |
| `pauseGame.png` | 暂停游戏标识（赌木成功触发） | 赌木暂停 | `CONFIRMED` |

### 2.2 Boss 模板库
- **`Images/boss/`**（51 个文件）：`01霍格.png` ~ `51奈法利安.png`。用于时光之穴 (SGZXBoss) 与常规 Boss 识别与选择。
- **`Images/chuanjiaobao/`**（17 个文件）：`01暴掠龙.png` ~ `17年兽.png`。用于传家宝 Boss (CJBBoss) 识别与选择。

### 2.3 技能与卡片模板库
- **`Images/skills/`**（16 个文件）：`asj` (奥术箭), `asjg` (奥术激光), `assx` (奥术射线), `bsxx`, `byj`, `dcw`, `dz`, `hbj`, `hq`, `jf`, `jq` (焦点), `ljf`, `pg` (瓦解光线), `sdl`, `tl`, `ys` 等技能简写模板。
- **`Images/cards/`**（36 个文件）：`baoji`, `chengzhang`, `dapao`, `dasheng`, `gongshen`, `liemoren`, `liliang`, `mingjie`, `shengming`, `zhanshen`, `zhili`, `zhufu` 等卡片选择模板。

---

## 3. 关键概念区分：原版局部模板 vs 当前全屏 Replay Fixture vs UI 变化

为防止在迁移过程中误用旧资产或产生语义混淆，必须严格区分以下三者：

```
+------------------------------------+------------------------------------+------------------------------------+
| 概念分类                            | 资源路径与形式                      | 使用边界与限制                      |
+------------------------------------+------------------------------------+------------------------------------+
| 1. 原版运行时局部模板                | 1.3.8/Images/*.png (如 80x30 小图) | 仅作名称、特征与回归比对参考；      |
| (Legacy Local Crop)                |                                    | 严禁直接作为当前全屏检测的唯一手段。|
+------------------------------------+------------------------------------+------------------------------------+
| 2. 当前项目全屏 Replay Fixture     | fixtures/reborn_wow/**/*.png       | 当前视觉检测、ROI 匹配、分差校验   |
| (Current Fullscreen Evidence)      | (1600x900 / 1920x1080 完整截图)    | 与 Dry-run 门禁回放的唯一权威来源。|
+------------------------------------+------------------------------------+------------------------------------+
| 3. 当前版本 UI 变化/需重验部分      | 见“当前版本人工补充最小清单”       | UI 布局、按钮尺寸或文本微调区域；  |
| (UI Variations requiring re-verify)|                                    | 必须由新截图验证后方可接入输入链。  |
+------------------------------------+------------------------------------+------------------------------------+
```

---

## 4. 原版行为与安全迁移矩阵

### 功能域 1：大厅 / 建房 / 房间等待 / 开始游戏
* **原版状态名/流程节点**：`PrimaryGameJob`, `GameRoom`, `GameSelector`
* **证据类型**：PDB 源文件名（`PrimaryGameJob.cs`, `GameRoom.cs`）、程序元数据（`GameMode`, `RoomName`, `RoomPassword`）、原版 HTML 说明（独狼/带队模式说明）、当前版本截图（`fixtures/reborn_wow/room/room_waiting_host.png`）
* **证据路径**：`1.3.8/GameScript.pdb`, `1.3.8/必读.html`, `fixtures/reborn_wow/room/room_waiting_host.png`
* **原版识别锚点**：大厅识别 `mainIdentifier.png`，房间等待 `startGameBtn.png`
* **原版可配置项**：`GameMode` (0=独狼, 1=带队, 2=赌木, 3=邪修秘境), `RoomName`, `RoomPassword`, `NewRoomEveryTimes`
* **原版默认行为**：独狼模式下点击创建房间，带队模式下填充房间名/密码并等待自动开始，非带队主动点击 `startGameBtn.png`
* **原版动作类型**：左键点击建房按钮 -> 键盘输入房间名/密码 -> 左键点击 `startGameBtn`
* **原版后置状态或超时行为**：进入选关/加载页面；等待超时由 `QueryTimeOut` (默认 60s) 监控，超时触发重试或异常抛出
* **当前版本对应状态**：`ROOM_WAITING` / `CREATE_ROOM`
* **当前版本状态**：`需当前截图验证`（房主等待页已存在 `room_waiting_host.png`，但快速加入/非房主模式需截图补充）
* **迁移优先级**：`P0-B` (High)
* **证据等级**：`CONFIRMED`

### 功能域 2：选关 / Stage1 / Stage2 / 可见关卡 / 开始主线
* **原版状态名/流程节点**：`SelectStageJob`, `StartMainLineJob`
* **证据类型**：PDB 源文件名（`SelectStageJob.cs`, `StartMainLineJob.cs`）、配置项（`Stage1`, `Stage2`）、当前版本截图（`fixtures/reborn_wow/stage/stage_select_old_world_1.png`, `stage_select_molten_core_2.png`）
* **证据路径**：`1.3.8/GameScript.exe.config`, `fixtures/reborn_wow/stage/`
* **原版识别锚点**：`stage.png`, `stage1.png`~`stage4.png` (大章节页签)，关卡列表行
* **原版可配置项**：`Stage1` (大章节序号，默认 `3`), `Stage2` (关卡行序号，默认 `2`)
* **原版默认行为**：点击 `Stage1` 对应大章节页签 -> 在可见列表中点击 `Stage2` 关卡行 -> 点击 `startGameBtn.png` 开始主线
* **原版动作类型**：左键点击大章节 -> 左键点击关卡行 -> 左键点击开始游戏
* **原版后置状态或超时行为**：验证目标行高亮/选中态 -> 转换至主线战局页面（`AutoGameJob`）；若无选中态禁止点击开始；超时 60s
* **当前版本对应状态**：`STAGE_SELECT` (`StageId(chapter, index)`)
* **当前版本状态**：`可直接复用`（新工程已在 P0-B 实现 `StageId` 章节+索引精确比较与选中态校验）
* **迁移优先级**：`P0-B` (High)
* **证据等级**：`CONFIRMED`

### 功能域 3：主线运行 / 自动任务 / 金币、木材、经验、宝物挑战
* **原版状态名/流程节点**：`AutoGameJob`, `MainStoryJob`
* **证据类型**：PDB 源文件名（`AutoGameJob.cs`, `MainStoryJob.cs`）、原版 HTML 说明（自动 F4, 5-5 触发）、当前版本截图（`fixtures/reborn_wow/main_line/main_line_auto_off.png`, `main_line_auto_on.png`）
* **证据路径**：`1.3.8/必读.html`, `fixtures/reborn_wow/main_line/`
* **原版识别锚点**：左下角四个挑战卡片（`tqtz.png`, `xzcz.png` 等）及其 `自动` 状态标签
* **原版可配置项**：`AutoCloseMainLine` (过完 5-5 自动清理怪物并关闭主线)，`CloseMainLineTime`
* **原版默认行为**：对左下角金币、木材、经验、宝物挑战卡片依次执行悬停+右键，开启自动挑战；5-5 波次触发 F4 清怪关闭主线
* **原版动作类型**：悬停 + 右键（Hover + Right Click）开启自动；键盘 `F4`
* **原版后置状态或超时行为**：卡片显示绿色 `自动` 标识；若已为绿色 `自动` 则不再重复右键
* **当前版本对应状态**：`MAIN_LINE_AUTO_OFF` -> `MAIN_LINE_AUTO_ON`
* **当前版本状态**：`可直接复用`（已在 `manifest.json` 中定义防重复右键 guard 并经过回放测试）
* **迁移优先级**：`P0-B` (High)
* **证据等级**：`CONFIRMED`

### 功能域 4：技能选择 / 卡片选择 / 羁绊 / 宝物 / 黑商
* **原版状态名/流程节点**：`AutoSkillJob`, `AutoCardJob`, `AutoGiftJob`, `AutoWeaponJob`
* **证据类型**：PDB 源文件名（`AutoSkillJob.cs`, `AutoCardJob.cs`, `AutoGiftJob.cs`, `AutoWeaponJob.cs`）、配置项（`Skills`, `Cards`, `AutoCard`, `AutoWeapon`, `DamageIncreaseCard`）、旧模板（`Images/skills/`, `Images/cards/`）、当前版本截图（`fixtures/reborn_wow/choices/`）
* **证据路径**：`1.3.8/Images/skills/`, `1.3.8/Images/cards/`, `fixtures/reborn_wow/choices/`
* **原版识别锚点**：三选一/四选一/五选一弹窗标题、`skill_hide.png`, `card_hide.png`, `woodgift.png`, `treasurechest.png`, `bbx.png`
* **原版可配置项**：`Skills` (如 `jq,pg`), `Cards` (如 `liliang,mingjie`), `AutoCard` (bool), `AutoWeapon` (bool), `DamageIncreaseCard` (奥数增伤：优先 `asjg`->`pg`, `assx`->`jq`)
* **原版默认行为**：按配置优先顺序匹配技能/卡牌图标；匹配失败时选择默认第一项或点击刷新（`cardRefresh.png`, `bwRefresh.png`）
* **原版动作类型**：左键点击选中的技能/卡牌卡片或刷新按钮
* **原版后置状态或超时行为**：选卡弹窗关闭，恢复战局循环
* **当前版本对应状态**：`SKILL_CHOICE`, `BOND_CHOICE`, `TREASURE_CHOICE`, `BLACK_MERCHANT_CARD_STRIP`
* **当前版本状态**：`需当前截图验证`（已覆盖三选一；四选一、五选一及全屏黑商仍需当前版本截图）
* **迁移优先级**：`P1` / `P2` (Medium)
* **证据等级**：三选一与技能/卡库为 `CONFIRMED`；四/五选一与黑商全屏状态为 `INFERRED`

### 功能域 5：胜利结算 / 继续游戏
* **原版状态名/流程节点**：`AutoWaitGameOverJob`
* **证据类型**：PDB 源文件名（`AutoWaitGameOverJob.cs`）、旧模板（`Images/continueGame.png`, `woodSuccess.png`）、当前版本截图（`fixtures/reborn_wow/endgame/victory_continue.png`）
* **证据路径**：`1.3.8/Images/continueGame.png`, `fixtures/reborn_wow/endgame/victory_continue.png`
* **原版识别锚点**：`continueGame.png` / `woodSuccess.png` （结算完成与“继续游戏”按钮）
* **原版可配置项**：`GameTimeOut` (单局最大超时，默认 `15` 分钟)
* **原版默认行为**：轮询检测到胜利/通关结算画面后，点击“继续游戏”按钮
* **原版动作类型**：左键点击“继续游戏”按钮
* **原版后置状态或超时行为**：进入局后 NPC 挑战广场 / 存档挑战面板；若超时 15 分钟触发超时警报
* **当前版本对应状态**：`POST_VICTORY`
* **当前版本状态**：`可直接复用`（已在 `victory_continue.png` 中验证并映射）
* **迁移优先级**：`P0-B` (High)
* **证据等级**：`CONFIRMED`

### 功能域 6：存档挑战 / 时光之穴 Boss
* **原版状态名/流程节点**：`AutoBossJob`
* **证据类型**：PDB 源文件名（`AutoBossJob.cs`）、配置项（`SGZXBoss`, `ArchiveBossTime`）、旧模板（`archiveChallenge.png`, `sgzxBoss.png`, `Images/boss/*.png`）、当前版本截图（`fixtures/reborn_wow/endgame/archive_challenge_panel.png`）
* **证据路径**：`1.3.8/Images/boss/`, `fixtures/reborn_wow/endgame/archive_challenge_panel.png`
* **原版识别锚点**：`archiveChallenge.png` (存档挑战面板), Boss 头像列表 (01霍格~51奈法利安)
* **原版可配置项**：`SGZXBoss` (指定时光之穴 Boss 名称), `ArchiveBossTime` (挑战时长/次数)
* **原版默认行为**：打开存档挑战面板 -> 点击所有可见且已解锁的存档挑战卡片 -> 若未配置 `SGZXBoss`，默认选择最后一个可见且可用的 Boss
* **原版动作类型**：左键点击 NPC -> 左键点击未解锁卡片 -> 左键点击 Boss 选择
* **原版后置状态或超时行为**：进入 Boss 战斗流程；战斗结束后返回 NPC 广场继续下一项
* **当前版本对应状态**：`ARCHIVE_CHALLENGE_PANEL`
* **当前版本状态**：`可直接复用`（面板与 Boss 选择逻辑已在 manifest 中定义 guard）
* **迁移优先级**：`P1` (Medium)
* **证据等级**：`CONFIRMED`

### 功能域 7：传家宝挑战 / 传家宝 Boss
* **原版状态名/流程节点**：`AutoBossJob`
* **证据类型**：PDB 源文件名（`AutoBossJob.cs`）、配置项（`CJBBoss`）、旧模板（`cjbtiaozhan.png`, `cjbBoss.png`, `Images/chuanjiaobao/*.png`）、当前版本截图（`fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png`）
* **证据路径**：`1.3.8/Images/chuanjiaobao/`, `fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png`
* **原版识别锚点**：`cjbtiaozhan.png` (传家宝挑战面板), 传家宝 Boss 图标 (01暴掠龙~17年兽)
* **原版可配置项**：`CJBBoss` (指定传家宝 Boss 名称/序号)
* **原版默认行为**：在 NPC 广场打开传家宝挑战 -> 若未配置 `CJBBoss`，默认选择最后一个可见且可用的传家宝 Boss
* **原版动作类型**：左键点击传家宝 NPC -> 左键点击目标 Boss（注意：界面中右键仅用于查看掉落详情，左键才是开启挑战）
* **原版后置状态或超时行为**：进入传家宝 Boss 战斗；战后返回 NPC 广场
* **当前版本对应状态**：`HEIRLOOM_CHALLENGE`
* **当前版本状态**：`可直接复用`（已验证左键开启、右键仅防误触查看掉落的规则）
* **迁移优先级**：`P1` (Medium)
* **证据等级**：`CONFIRMED`

### 功能域 8：英雄挑战 / 大秘境 / 大秘境确认
* **原版状态名/流程节点**：`AutoHeroJob`
* **证据类型**：PDB 源文件名（`AutoHeroJob.cs`）、配置项（`AutoSecretRealm`）、旧模板（`HeroChallenge.png`, `damijing.png`, `mijingOk.png`）、当前版本截图（`fixtures/reborn_wow/endgame/great_rift_confirm.png`）
* **证据路径**：`1.3.8/GameScript.exe.config`, `fixtures/reborn_wow/endgame/`
* **原版识别锚点**：左上角 `HeroChallenge.png` 英雄挑战图标、大秘境对话框 `damijing.png`、确认按钮 `mijingOk.png`
* **原版可配置项**：`AutoSecretRealm` (bool, 默认 `False`)
* **原版默认行为**：当 `AutoSecretRealm=True` 且地图所有挑战完成、无存活 Boss 且左上角 `HeroChallenge.png` 可见时 -> 右键大秘境 NPC -> 在确认弹窗中左键点击“是”
* **原版动作类型**：右键点击大秘境 NPC -> 左键点击“是” (`mijingOk`)
* **原版后置状态或超时行为**：进入大秘境战斗循环，直至大秘境失败或退出
* **当前版本对应状态**：`GREAT_RIFT_CONFIRM`
* **当前版本状态**：`可直接复用`（前置条件与确认弹窗已在 manifest 中建立严密依赖规则）
* **迁移优先级**：`P1` (Medium)
* **证据等级**：`CONFIRMED`

### 功能域 9：退出游戏 / 断线 / 重试 / 超时
* **原版状态名/流程节点**：`AutoWaitGameOverJob`, `GRetry.cs`, `EnvironmentUtils.cs`
* **证据类型**：PDB 源文件名（`GRetry.cs`, `AutoWaitGameOverJob.cs`）、配置项（`GameTimeOut`, `QueryTimeOut`）、旧模板（`quit.png`, `gameDisconnect.png`, `retryConnect.png`）、HTML 说明（Shift+F12 紧急停止）
* **证据路径**：`1.3.8/Images/quit.png`, `1.3.8/Images/gameDisconnect.png`, `1.3.8/必读.html`
* **原版识别锚点**：左上角 `quit.png`、断线弹窗 `gameDisconnect.png`、重连按钮 `retryConnect.png`
* **原版可配置项**：`GameTimeOut` (单局超时时间，默认 `15` 分钟), `QueryTimeOut` (节点超时，默认 `60` 秒)
* **原版默认行为**：主动退出时点击左上角 `quit.png`；检测到断线弹窗时点击 `retryConnect.png` 尝试重连；单局超过 `GameTimeOut` 触发通知/强平；按 `Shift+F12` 立即终止进程
* **原版动作类型**：左键点击退出/重连；`Shift+F12` 全局热键急停
* **原版后置状态或超时行为**：退出游戏返回大厅或重启游戏；全局急停立即切断所有输入
* **当前版本对应状态**：`QUIT` (已在 P0-B 验证), `DISCONNECT` (缺当前版本全屏截图)
* **当前版本状态**：`需当前截图验证`（退出按钮已复用；全屏断线与重连弹窗需要补充当前截图）
* **迁移优先级**：`P0-B` / `P1` (High)
* **证据等级**：退出与超时行为为 `CONFIRMED`；当前版本断线弹窗布局为 `INFERRED`

### 功能域 10：配置项优先级与默认策略
* **原版配置项全集**：`CJBBoss`, `SGZXBoss`, `Skills`, `Cards`, `AutoSecretRealm`, `Stage1`, `Stage2`, `ArchiveBossTime`, `GameTimeOut`
* **证据类型**：`GameScript.exe.config` XML 配置、`JsonSettingsBase.cs`、`必读.html`
* **证据路径**：`1.3.8/GameScript.exe.config`, `1.3.8/必读.html`
* **优先级与默认策略规则**：
  1. **显式配置优先于默认降级**：例如当 `CJBBoss` 或 `SGZXBoss` 指定具体名称（如 `"02血腥猛犸"`）时，优先匹配该名称；若为空或未配置，则回退为默认选择界面中**最后一个可见且启用的 Boss**（`last_visible_enabled_boss`）。
  2. **无效配置安全兜底**：若配置的目标 Boss 或技能在当前 UI 中未找到或被锁，必须 Fail-Safe 记录日志并回退默认或停止动作，严禁盲目点击固定坐标。
  3. **功能开关强门禁**：`AutoSecretRealm` 默认值必须为 `False`；仅当显式设为 `True` 且满足“无存活 Boss + 英雄挑战标识可见”三大前置条件时方可触发。
  4. **关卡选关防越界**：`Stage1`（默认 `3`）和 `Stage2`（默认 `2`）映射具体章节与行。若账号未解锁对应关卡，必须 Fail-Safe 拒绝点击开始。
  5. **单局超时狗**：`GameTimeOut`（默认 `15` 分钟）作为单局最大运行守卫，超时后触发安全清理或通知，防止脚本死循环卡死。
  6. **技能与卡片优先级**：`Skills`（默认 `"jq,pg"`）按配置字符串解析顺序依次匹配模板，若全无匹配则选择第一项或点击刷新按钮。
* **迁移优先级**：`P0-B` / `P1` (High)
* **证据等级**：`CONFIRMED`

---

## 5. 当前版本人工补充最小清单

以下清单仅列出**真正无法从原版 1.3.8 恢复、且会阻止当前版本自动化验收**的内容：

1. **当前版本完整退出 / 断线确认弹窗全屏截图**
   - **用途**：用于 P0-B 回放测试门禁中的 `missing_disconnect_modal` 补全，确保在网络抖动或异常退出时能安全识别并执行重连/退出。
2. **当前版本完整黑商状态全屏截图**
   - **用途**：替换现有仅 350x88 局部裁剪的 `black_merchant_card_strip.png`，建立完整的黑市购买场景识别与防误触安全边界。
3. **四选一与五选一技能选择界面全屏截图**
   - **用途**：当前截图库仅有三选一 (`skill_choice_3.png`)；在账号解锁高阶技能选择后，需要四选一和五选一的布局图以适配坐标计算与选卡策略。
4. **当前账号实际要刷的目标关卡视图全屏截图**
   - **用途**：如当前账号配置刷 `4-2` 或 `5-10`，需提供对应章节翻页及目标关卡行高亮的真实截图，用于选关模块的端到端回放验证。

---

## 6. 总结与后续推进路线

1. 原版 1.3.8 提供了极其丰富和完整的状态机、Boss/技能模板词典及配置项逻辑；
2. 本迁移矩阵已完成 10 大功能域的证据提炼，新工程保留 `P0-A` 的 HWND 绑定、窗口身份校验、急停与安全执行链；
3. 后续功能开发严格遵循：**原版行为提炼 → 当前 UI 截图验证 → 安全代码迁移 → Replay 回放验收** 的闭环推进。
