# P1-B0 战后状态只读建模与 Replay 证据闭环

> 范围：只读建模。本阶段不发送任何真实输入，不修改任何用户素材。
> 证据来源：`fixtures/reborn_wow/endgame/` 5 张当前版本全屏截图 + `tools/analyze_post_game.py` 只读诊断 + 1.3.8 原版逆向事实。
> 基线：`e5809b1`（H0 验收通过）。

## 1. 结论先行

1. 五张战后截图（胜利结算、存档面板、NPC 广场、传家宝 Boss 弹窗、大秘境确认弹窗）在**当前 Mediator 下全部产生零输入**：`_tick_main_line` 在 `archive` / `boss_entry` 锚点命中后 Fail-Closed 停机（`Phase.ERROR` + `Break`），已由 `tests/test_p1b0_post_game.py` 固化。
2. 五张截图已按“观察专用（observe-only）”条目接入根 `fixtures/manifest.json`（`expected_action: none`），Replay 门禁 `Total=32, Passed=31, Failed=0, Required Missing=1`（唯一缺口仍为 `missing_disconnect_modal`）。
3. **关键发现**：`archive` 场景模板在当前版本 UI 上匹配的是**战后页面共用的顶部 HUD 元素**（约 `(680,55)`，score 0.955，五张图一致），不是存档面板的专有特征；`boss_entry`、`secret`、`close`、`ok` 同理命中共用 HUD/底栏元素。因此**现有模板不能区分战后各页面** —— P1-B1 前必须先补页面级专有锚点（见 §7 决策点）。
4. 1.3.8 原版为 **Costura 打包 + 重度混淆 + 资源加密**：主模块 IL 可读但方法名混淆；真实 Job 代码封装在加密内嵌程序集中，不运行原版 EXE 无法静态解出（遵守项目“不运行原版”约束）。已提取的可用证据：60+ 配置键面、PDB 源文件清单、267 张模板清单。

## 2. 页面证据表（tools/analyze_post_game.py 实测）

模板匹配阈值：场景锚点 0.55（低阈值探针），页面判级按 0.70。坐标为客户区像素。

| 页面 | 当前 context | 判级 | 专有/最强锚点（score @ 位置） | 共用 HUD 命中（不可作页面判据） |
|---|---|---|---|---|
| `victory_continue` 胜利结算 | MAIN_LINE | CONFIRMED | `continueGame` 0.874 @ (800,587)（继续游戏按钮）；`close` 0.995 @ (1000,242)（结算弹窗关闭） | archive 0.955 @(684,58)、boss_entry 0.821、secret 0.713、HeroChallenge 0.944 |
| `archive_challenge_panel` 存档面板 | MAIN_LINE | CONFIRMED | `archiveChallenge` 0.945 @ (798,45)（存档标签）；`close` 1.000 @ (996,239)（面板关闭）；`longzhu` 0.560 @ (714,209)（可疑：共用元素低分命中） | archive 0.955、boss_entry 0.821、secret 0.713 |
| `challenge_npc_hub` NPC 广场 | UNKNOWN | CONFIRMED | `damijing` 0.930 @ (1132,307)（大秘境 NPC）；`HeroChallenge` 0.944 @ (351,116)（左上英雄挑战标）；`quit` 0.878 @ (75,52)（左上退出） | archive 0.955、boss_entry 0.821、ok 0.701 |
| `heirloom_challenge_bosses` 传家宝弹窗 | UNKNOWN | CONFIRMED | `cjbtiaozhan` 0.976 @ (799,246)（传家宝弹窗横幅）；`close` 0.969 @ (989,245)（弹窗关闭） | archive 0.970、boss_entry 0.821、secret 0.930 |
| `great_rift_confirm` 大秘境确认 | UNKNOWN | CONFIRMED | `mijingOk` 0.910 @ (714,478) + `ok` 0.932 @ (715,478)（确认按钮）；`damijing` 0.930 @ (1134,310)（秘境入口图标） | archive 0.955、boss_entry 0.821、quit 0.878 |

判级规则：任一锚点 ≥0.70 即 CONFIRMED；有命中但 <0.70 为 INFERRED；无命中为 UNKNOWN。**判级仅证明“页面含这些元素”，不证明“页面身份唯一”** —— 页面身份判定需专有锚点组合（§7 决策点 1）。

## 3. 状态转换图（当前只读目标链）

```mermaid
flowchart TD
    ML[MAIN_LINE 局内] -->|胜利结算出现| VIC[POST_VICTORY 胜利结算<br/>continueGame@0.874]
    VIC -->|P1-B1: 点击继续游戏 前置:continueGame 命中 后置:NPC广场| HUB[CHALLENGE_NPC_HUB<br/>damijing@0.93 + HeroChallenge@0.94]
    HUB -->|左键 存档NPC| ARCH[ARCHIVE_CHALLENGE_PANEL<br/>archiveChallenge@0.945]
    HUB -->|左键 传家宝NPC| HEIR[HEIRLOOM_CHALLENGE<br/>cjbtiaozhan@0.976]
    HUB -->|右键 大秘境NPC<br/>前置:三条件| RIFT[GREAT_RIFT_CONFIRM<br/>mijingOk@0.91 / ok@0.93]
    VIC -.->|当前实现| FC[Fail-Closed 停机 零输入]
    ARCH -.->|当前实现| FC
    HEIR -.->|当前实现| FC
    RIFT -.->|当前实现| FC
    HUB -.->|当前实现| FC
```

虚线 = 当前已固化的行为（全部零输入）；实线 = P1-B1 候选链（未批准前不得执行）。

## 4. 各入口前置 / 禁点 / 后置（依据用户规则，均为 CONFIRMED 用户事实）

| 入口 | 前置条件 | 禁点区域 | 后置确认 |
|---|---|---|---|
| 胜利→继续游戏 | `continueGame` 模板命中（0.85+） | 左上 `quit` 区 (40,20,90,60) 永不作恢复猜点 | 页面变为 NPC 广场（damijing 命中） |
| 存档挑战 | `archiveChallenge` 命中；仅点可见且解锁卡片，不按固定数量 | 锁定卡片；`longzhu`/`secret` 邻近误触 | 面板关闭 / 挑战开始证据 |
| 传家宝 Boss | `cjbtiaozhan` 命中；选择配置 Boss 或最后可见启用 Boss | 弹窗内**禁止右键**（右键=掉落详情） | 挑战开始证据 |
| 大秘境 | 三前置：地图挑战全清 + 无存活 Boss + `HeroChallenge` 可见（当前截图仅能确认第三条） | 无 `HeroChallenge` 时禁止一切秘境输入 | 确认弹窗 `mijingOk` 命中后才能点“是” |
| 退出 | 任何局内态，仅用户主动决定退出时 | 不得作为故障恢复手段 | — |

## 5. 逆向 1.3.8 新增事实（相对 ORIGINAL_1_3_8_BEHAVIOR_MATRIX.md）

1. **打包/混淆结构**：`GameScript.exe` 为 Costura.Fody 单文件宿主（61 个内嵌资源，含 OpenCvSharp、SignalR、HandyControl、Lan.UIAutomation 等）；主模块 138 个类型、1030 个方法，方法名重度混淆（随机大小写），`#US` 堆几乎为空；两枚混淆自定义资源（`OEYBMpZU…` 主程序集、`VqGxZ6ot…`）**静态不可解**（高熵加密，非 zlib/LZMA），解出需运行原版 EXE（项目禁止）→ 战后 Job（`AutoWaitGameOverJob`/`AutoBossJob`/`AutoHeroJob`/`GRetry` 等）的 IL 级序列**保持 UNKNOWN**。
2. **配置面扩充**（主模块 Settings 属性可读，全部 CONFIRMED 存在于程序集）：除矩阵 13 键外新增 —— `NeedSelectBoss`、`NextCardGroup`、`NumberOfScroll`、`KillBossNum`、`BoosLiveTime`(原版拼写)、`HasMainForce`、`AutoGamblingTime`、`AutoCleanInterval`、`AutoReputation`、`ContinueReputation`、`ReputationCJBBoss/SGZXBoss/Stage1/Stage2/Level1-6`、`SanlingFirst`、`TreasureNum`、`Electrify`、`SwordIncreasedDamaged`、`DevelopTime/Priority`、`CycleNum`、`MouseOperationInterval`、`MoveWindow`、`OnlyTransferWhenMultiGame`、`FindLongzhuWhereMultiGame`、`StageSelectInterval`、`CleanReputationDate`、`CertEnable`。**行为语义 UNKNOWN**（无 IL 佐证）。
3. **PDB 源文件清单**（较矩阵新增）：`InfiniteBossJob.cs`、`AutoReputationJob.cs`、`AutoFindWoodJob.cs`、`AutoCleanJob.cs`、`MultiGame.cs`、`GameStatus.cs`、`MainViewModel.cs`、`ProcessHelper.cs`、`LogHelper.cs`、`ArchaeoProtection.cs`（考古/防沉迷相关）。
4. **模板实证**：1.3.8 旧模板在当前版本截图上**高置信命中**（0.87–0.98），证实原版素材可作为特征词典；但命中集中在战后页面共用的 HUD/底栏元素，单独使用不足以判页（与矩阵“仅作参考”结论一致且得到量化支持）。

## 6. 验收

- `python tools/analyze_post_game.py`：5/5 页面 `would_click=False`，判级 CONFIRMED。
- `tests/test_p1b0_post_game.py`：7/7 OK（Fail-Closed 零输入 ×5 页面、observe-only 门禁 ×5、专有锚点 ×5）。
- Replay 门禁：`Total=32, Passed=31, Failed=0, Required Missing=1`（`missing_disconnect_modal` 不变）。
- 全量回归：`Ran 107 tests OK`（原 100 + 新 7）；`validate_scenes ok=99 missing=0 root_unreferenced=0`；`compileall` 通过。

## 7. P1-B1 前置决策点（需要项目负责人拍板 / 补充资料）

1. **页面专有锚点**：当前模板无法区分战后页面；需用当前版本截图裁剪专有小图（存档标签、传家宝横幅、秘境确认按钮、继续游戏按钮、NPC 名称/图标）建立页面级场景，或接受“多锚点组合判定”方案。
2. **大秘境前置运行时校验**：截图仅能证明 `HeroChallenge` 可见；“地图挑战全清”“无存活 Boss”为运行时状态，需定义可机检的证据（模板/状态机）后才能谈输入。
3. **胜利→继续游戏是否解封**：P1-B0 仅证明“不误触”；解封 `continueGame` 左键属于 P1-B1 范围，需负责人显式批准（仍保持 dry_run）。
4. **断线弹窗素材**：`missing_disconnect_modal` 仍缺，根门禁 exit 1 维持；与 P1-B1 无依赖。
5. **原版 Job IL 级证据**：如需 `AutoWaitGameOverJob` 等精确序列（超时、重试次数、坐标），需负责人授权运行原版 EXE（当前约束禁止）或提供反混淆工具白名单。
