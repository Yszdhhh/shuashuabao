# 竞品1 (GameScript) Settings 74 配置 × 函数调用映射全景表

> **真源文件**：`C:\Users\10639\Desktop\竞品\竞品分析资产\01_参考脚本1更新\反编译源码\GameScript.Models\Settings.cs`  
> **关联调用**：`GameScript.Jobs.AutoJob.cs`、`LongzhuJob.cs`、`CardGroup.cs`  
> **整理日期**：2026-09-23  
> **价值定位**：全量揭秘竞品1全部 74 个公开配置项、默认参数、所属模块、底层驱动函数以及对我方（ShuaBao）的架构裁决。

---

## 一、 配置分组全景与功能映射表

### 1. 大厅、房间与多开模式 (L0 / S1)

| 配置字段 | 类型 | 默认值 | 关联方法/逻辑 | 竞品行为解释 | 刷刷宝裁决 (ADAPT/REF/REJECT) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `RoomName` | string | `""` | `AutoJob.FindRoom()` | 自建房房名过滤匹配 | **ADAPT**：用于找房模式 |
| `RoomPassword` | string | `"111"` | `AutoJob.CreateRoom()` | 自建房间密码输入 | **ADAPT**：已实现 UIA 输入 |
| `NewRoomEveryTimes`| bool | `false`| `AutoJob.OnRoundEnd()` | 战后退出房间重新建房 | **ADAPT**：有效防止长期房间内存泄漏 |
| `GameMode` | int | `0` | `AutoJob.Run()` | 模式枚举（0单人,1带队,2赌木,3邪修） | **ADAPT**：我方分流 solo/hitch/reputation |
| `FollowTheLead` | bool | `false`| `AutoJob.CheckHost()` | 混车模式开启：跟随房主进度与指令 | **ADAPT**：混车从动核心 |
| `MoveWindow` | bool | `false`| `PowerHelper.MoveWindow()`| 自动将游戏窗移动至屏幕 (0,0) 并锁定 1600x900 | **REJECT**：强制锁屏破坏多分辨率兼容 |
| `RoomTimedOutAndExited`| int | `0` | `AutoJob.WaitRoomTimeout()`| 房间停留超时后自动退出秒数 | **ADAPT**：大厅防卡死超时保护 |
| `QueryTimeOut` | int | `200` | `AutoJob.WaitResponse()`| 网络查询或控件响应超时(ms) | **REF**：我方有专用 action lease |
| `CertEnable` | bool | `false`| `LicenseManager.Verify()`| 在线卡密/机器码鉴权开关 | **REF**：商业化体系对照 |
| `LicenseTxt` | string | `""` | `LicenseManager.Load()` | 授权激活码存放 | **REF**：我方有独立 permit 体系 |

### 2. 局内主线推进与发育节奏 (L0 / S2)

| 配置字段 | 类型 | 默认值 | 关联方法/逻辑 | 竞品行为解释 | 刷刷宝裁决 (ADAPT/REF/REJECT) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `Stage1` | int | `3` | `AutoJob.SelectLevel()` | 章节选择（如第3章） | **ADAPT**：选关参数 |
| `Stage2` | int | `2` | `AutoJob.SelectDifficulty()` | 难度选择（如难度2） | **ADAPT**：难度参数 |
| `StageSelectInterval`| int | `0` | `AutoJob.DelaySelect()` | 选关点击间歇延迟(ms) | **REF**：防封号随机抖动 |
| `AutoCloseMainLine` | bool | `false`| `AutoJob.ToggleMainLine()` | F4 关主线，清怪保命 | **ADAPT**：主 C 压力大时关主线 |
| `CloseMainLineTime` | int | `0` | `AutoJob.ScheduleCloseMain()`| 开局多少秒后强制关闭主线 | **ADAPT**：定时关主线功能 |
| `DevelopTime` | int | `0` | `AutoJob.DevelopLoop()` | 开局纯发育等待时长(秒) | **REF**：战前发育窗口 |
| `DevelopPriority` | bool | `false`| `AutoJob.DevelopFirst()` | 发育优先于挑战 Boss | **REF**：战力策略权重 |
| `HasMainForce` | bool | `false`| `AutoJob.CheckCarOwner()` | 当前队伍是否存在主力大 C | **ADAPT**：用于混车从动降载 |
| `OnlyTransfer` | bool | `false`| `AutoJob.ClickTransfer()` | 仅点击压力转移，不打主线 | **ADAPT**：混车站桩工具人模式 |
| `OnlyTransferWhenMultiGame` | bool | `false`| `AutoJob.MultiTransfer()` | 多开时只做压力转移 | **ADAPT**：低配置多开策略 |
| `GameTimeOut` | int | `15` | `AutoJob.WatchdogTick()` | 单局最大超时时间(分钟)，超时强制重开 | **ADAPT**：单局硬限超时 (Round Watchdog) |

### 3. 经济、黑商与赌木 (L1 / S3)

| 配置字段 | 类型 | 默认值 | 关联方法/逻辑 | 竞品行为解释 | 刷刷宝裁决 (ADAPT/REF/REJECT) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `AutoGamblingTime` | int | `0` | `AutoJob.GambleWood()` | 赌木触发时间点或间隔(秒) | **ADAPT**：支持定时赌木 |
| `AutoCleanInterval` | int | `5` | `AutoJob.CleanInventory()`| 物品栏清理/分解/合成周期(分钟) | **ADAPT**：背包清理定时器 |
| `BoosLiveTime` | int | `0` | `AutoJob.EvilRealmTick()` | 邪修秘境 Boss 存活监控超时 | **REF**：秘境专项计时 |
| `KillBossNum` | int | `0` | `AutoJob.KillBossCount()` | 累计击杀 Boss 计数门槛 | **REF**：局数/进度计数器 |
| `CycleNum` | int | `0` | `AutoJob.LoopCount()` | 当前循环执行轮数 | **REF**：统计看板 |

### 4. 技能构筑与卡牌选取 (L1 / S4)

| 配置字段 | 类型 | 默认值 | 关联方法/逻辑 | 竞品行为解释 | 刷刷宝裁决 (ADAPT/REF/REJECT) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `Skills` | List<string> | `[]` | `CardGroup.SelectSkill()`| 勾选的优先技能清单 | **ADAPT**：技能白名单 |
| `Cards` | List<string> | `[]` | `CardGroup.SelectCard()` | 勾选的优先羁绊卡清单 | **ADAPT**：羁绊卡白名单 |
| `AutoCard` | bool | `false`| `CardGroup.TickCard()` | 自动抽取与购买羁绊卡总开关 | **ADAPT**：F 键开关 |
| `AutoWeapon` | bool | `false`| `CardGroup.TickWeapon()` | 自动进行武器强化/洗练总开关 | **ADAPT**：武器开关 |
| `SingleSelectedSkill` | string | `""` | `CardGroup.FocusSkill()`| 单独锁定的核心主修技能 | **ADAPT**：如专精奥术箭 |
| `ASJJSFirst` | bool | `false`| `CardGroup.PickASJJS()` | 奥术箭急速（关键质变）第一优先级 | **ADAPT**：完全吻合 23 级质变断崖 |
| `SanlingFirst` | bool | `false`| `CardGroup.PickSanling()`| 三灵羁绊优先拿取 | **REF**：特定流派规则 |
| `SwordIncreasedDamaged`| bool | `false`| `CardGroup.PickSword()` | 剑气增伤卡优先 | **ADAPT**：剑气流派标签 |
| `ChainIncreasedDamaged`| bool | `false`| `CardGroup.PickChain()` | 闪电链增伤卡优先 | **ADAPT**：闪电流派标签 |
| `ICEIncreasedDamaged` | bool | `false`| `CardGroup.PickIce()` | 寒冰箭增伤卡优先 | **ADAPT**：冰系流派标签 |
| `HQIncreasedDamaged` | bool | `false`| `CardGroup.PickHQ()` | 火球增伤卡优先 | **ADAPT**：火球流派标签 |
| `SXIncreasedDamaged` | bool | `false`| `CardGroup.PickSX()` | 射线增伤卡优先 | **ADAPT**：射线流派标签 |
| `JGIncreasedDamaged` | bool | `false`| `CardGroup.PickJG()` | 激光增伤卡优先 | **ADAPT**：激光流派标签 |
| `DZIncreasedDamaged` | bool | `false`| `CardGroup.PickDZ()` | 地震增伤卡优先 | **ADAPT**：地震流派标签 |
| `Electrify` | bool | `false`| `CardGroup.PickElec()` | 感电卡优先 | **ADAPT**：雷电联动标签 |
| `TreasureNum` | int | `0` | `CardGroup.PickTreasure()`| 宝物抽取上限计数 | **REJECT**：宝物受资源约束非固定次数 |
| `EvilTreasureMode` | int | `0` | `CardGroup.EvilTreasure()`| 邪修特化宝物模式枚举 | **REF**：特异流派参考 |

### 5. 神器与龙珠互动 (L1 / S5)

| 配置字段 | 类型 | 默认值 | 关联方法/逻辑 | 竞品行为解释 | 刷刷宝裁决 (ADAPT/REF/REJECT) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ArtifactMode` | int | `0` | `AutoJob.UseArtifact()` | 神器释放模式（0关,1开1槽,2开2槽,3全开） | **ADAPT**：槽位选择 |
| `ArtifactDelay` | int | `0` | `AutoJob.ArtifactTimer()`| 神器释放延迟/轮询冷却(ms) | **ADAPT**：定时释放 |
| `DragonBallCount` | int | `7` | `LongzhuJob.Collect()` | 龙珠寻找目标数量（默认打满 7 颗） | **ADAPT**：龙珠收集上限 |
| `FindLongzhuInGame` | bool | `false`| `LongzhuJob.Search()` | 局内主线中开启龙珠寻找 | **ADAPT**：局内寻找 |
| `FindLongzhuWhereMultiGame`| bool| `false`| `LongzhuJob.MultiSearch()`| 多开模式下开启龙珠寻找 | **ADAPT**：多开开关 |
| `FindGiftWhenMultiGame` | bool | `false`| `AutoJob.FindGift()` | 多开时寻找并领取地图礼包 | **ADAPT**：福利领取 |

### 6. 战后链、Boss挑战与秘境 (L0 / S6)

| 配置字段 | 类型 | 默认值 | 关联方法/逻辑 | 竞品行为解释 | 刷刷宝裁决 (ADAPT/REF/REJECT) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ArchiveBossTime` | int | `0` | `AutoJob.PostGameBoss()`| 存档/传家宝挑战窗口总预算（秒） | **ADAPT**：对齐我方战后预算 |
| `NeedSelectBoss` | bool | `false`| `AutoJob.SelectBoss()` | 是否需要主动在弹窗中挑选 Boss | **ADAPT**：Boss 挑战总门控 |
| `CJBBoss` | string | `"15猛虎之神"`| `AutoJob.PickCJBBoss()` | 传家宝目标 Boss 名称 | **ADAPT**：传家宝目标单源 |
| `SGZXBoss` | string | `"39拉格纳罗斯"`| `AutoJob.PickSGZXBoss()`| 时光之穴目标 Boss 名称 | **ADAPT**：时光之穴目标单源 |
| `SmallCJBoss` | string | `"15猛虎之神"`| `AutoJob.PickSmallBoss1()`| 关卡分层挑战 Boss 1 | **ADAPT**：多阶段 Boss 映射 |
| `SmallCJBoss2` | string | `"15猛虎之神"`| `AutoJob.PickSmallBoss2()`| 关卡分层挑战 Boss 2 | **ADAPT**：多阶段 Boss 映射 |
| `SmallCJBoss3` | string | `"15猛虎之神"`| `AutoJob.PickSmallBoss3()`| 关卡分层挑战 Boss 3 | **ADAPT**：多阶段 Boss 映射 |
| `SmallCJBCustomSetting`| bool | `false`| `AutoJob.EnableCustomBoss()`| 启用分层自定义 Boss 开关 | **ADAPT**：高级配置开关 |
| `NumberOfScroll` | int | `0` | `AutoJob.ScrollBossList()`| 选取高位 Boss 时滚轮滑动次数 | **ADAPT**：虚拟网格滚动映射 |
| `AutoSecretRealm` | bool | `false`| `AutoJob.EnterRealm()` | 自动进入秘境挑战 | **ADAPT**：秘境开关 |
| `ContinueMiJing` | bool | `false`| `AutoJob.LoopRealm()` | 秘境通关后继续下一层秘境 | **ADAPT**：连续秘境循环 |
| `CleanMiJingDate` | DateTime | default | `AutoJob.ResetRealmRecord()`| 秘境日常次数清理基准时间 | **REF**：日常重置 |
| `AutoReputation` | bool | `false`| `AutoJob.RunReputation()` | 自动刷声望模式开关 | **ADAPT**：声望玩法支持 |
| `ContinueReputation` | bool | `false`| `AutoJob.LoopReputation()`| 声望满级前持续循环挑战 | **ADAPT**：声望连刷 |
| `ReputationEffect` | bool | `false`| `AutoJob.ReputationBuff()`| 领取声望加成奖励 | **ADAPT**：声望奖励 |
| `ReputationLevel1`~`6` | int | `0` | `AutoJob.ReputationGoal()`| 六大阵营声望目标等级设定 | **ADAPT**：阵营声望配置 |
| `ReputationStage1`/`2`| int | `0` | `AutoJob.ReputationMap()` | 声望专属章节与难度 | **ADAPT**：声望地图 |
| `ReputationCJBBoss` | string | `""` | `AutoJob.ReputationCJB()` | 声望专用传家宝 Boss | **ADAPT**：声望专用 Boss |
| `ReputationSGZXBoss` | string | `""` | `AutoJob.ReputationSGZX()`| 声望专用时光之穴 Boss | **ADAPT**：声望专用 Boss |
| `CleanReputationDate`| DateTime| default | `AutoJob.ResetRepDate()` | 声望周期刷新日期记录 | **REF**：周期重置 |

### 7. 辅助与底层交互控制 (Hardware & Notification)

| 配置字段 | 类型 | 默认值 | 关联方法/逻辑 | 竞品行为解释 | 刷刷宝裁决 (ADAPT/REF/REJECT) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `BatFile` | string | `""` | `AutoJob.ExecuteBat()` | 触发飞书/群通知的本地批处理脚本路径 | **ADAPT**：飞书 Webhook 告警 |
| `MouseOperationInterval`| int | `0` | `PowerHelper.Sleep()` | 鼠标各动作间的强制睡眠等待(ms) | **REF**：我方有专用 cooldown 规范 |
| `LegacyMode` | bool | `false`| `AutoJob.LegacyInput()` | 兼容老版本操作模式 | **REJECT**：无维护价值 |

---

## 二、 架构深度总结与 ShuaBao 看板暴露建议

1. **竞品 Settings 最大的亮点**：
   * 将「战后 Boss 挑战时间」(`ArchiveBossTime`) 与「单局超时」(`GameTimeOut`) 清晰解耦，直观呈现给用户；
   * 细化了「小关卡分层挑战 Boss」(`SmallCJBoss 1/2/3`)，满足了用户在前期低战力打 15 猛虎之神、中后期战力成型切 39 拉格纳罗斯的弹性诉求。
2. **ShuaBao 应当吸纳的 UI 看板配置项**：
   * 在 `ui-v2` 设置页面补全：`每局新房 (NewRoomEveryTimes)`、`混车自动压力转移 (OnlyTransfer)`、`关卡分层传家宝 Boss 切换` 与 `飞书通知 Webhook`。
