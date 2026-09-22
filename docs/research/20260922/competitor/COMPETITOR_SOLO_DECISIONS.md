# 竞品「单人局内决策」静态调研（2026-09-22）

## 证据边界

- **竞品侧**：`C:\Users\10639\Desktop\竞品\竞品分析资产\01_参考脚本1更新\反编译源码\`（既有落库反编译，只读）、`C:\Users\10639\Desktop\竞品\脚本1更新\1.6.2\`（包面/配置/HTML）、`C:\Users\10639\Desktop\竞品\竞品分析资产\02_参考脚本3\`（字节码+分析报告，只读引用）。
- **未运行竞品 EXE/脚本，未发游戏输入，未做新的反编译。**
- **Boss/时光之穴/传家宝/命运骰子/神器/ArchiveBossTime** 部分已在 `COMPETITOR_STATIC_OBSERVATIONS_1_6_2_20260922.md` 写过，本文**不重复**，仅在配置键表中列名。
- **我方实机 GT 对照**（仅主题②一行）：`G:\刷刷宝\_facts_20260922\treasure_debuff_frames\`（report.md + treasure_catalog.md + 25 帧，96 卡 / 负面 19）。
- 证据类型标注：`[反编译]` = 落库反编译源码 file:line；`[配置]` = GameScript.exe.config / Settings.cs 字段；`[包面]` = 1.6.2 资源/HTML；`[脚本3]` = 脚本3 字节码/分析报告；`[推断]` = 静态推断，待实机验证。

---

## 1. 摘要（≤10 条）

1. **羁绊用「物种链」模型**：`CardGroup{SpeiceName, Images[], NextCardGroup, Priority}`，用户 `Settings.Cards` 有序列表即优先级；每成功点掉一张卡从 `Images` 移除一项，耗尽后提升 `NextCardGroup`（进化链）。`[反编译] CardGroup.cs:8-88; H9w4YXUwUCCOSsJMsLL.cs:668-787`
2. **两层名字（卡头「祝福(2/3)」vs 卡名「智力祝福」）竞品完全不读卡头**：只模板匹配**卡名**图（如 `tishu`/`zhanshu`/`shengming`），进度靠 `Images` 列表长度递减，不 OCR「(2/3)」。脚本3 则把卡头编码进目录名 `good_cards/1_祝福_3/`。`[反编译] H9w4YXUwUCCOSsJMsLL.cs:129-207; [脚本3] COMP3_ASSET_CATALOG.csv:66`
3. **卡组刷新上限 8 次**，超限打日志退出；卡槽容量 10，≥9 张先吃丹药（`danGif`）腾位，无丹药则跳出先选宝物。`[反编译] H9w4YXUwUCCOSsJMsLL.cs:903-968`
4. **宝物只有优先白名单，无负面禁拿名单**：`LongzhuJob` 两套列表（默认/DevelopPriority）+ `Q4Qf1OB0kqbcIxuImlQ` 宝物三选一列表；找不到目标就 `giveUp`。竞品不做红字/描述判定。`[反编译] LongzhuJob.cs:16-49; Q4Qf1OB0kqbcIxuImlQ.cs:42-57`
5. **黑商逻辑只在脚本3**（脚本1 反编译无）：黑市 `MARKET_GOODS_ZONE` 买「宝物刷新次数」和「吞噬丹」，H 刷新，同位 3 连点仍在=资源不足停，2 次像素无变化→10s 冷却。`[脚本3] main_dis.txt:54552-55287; COMP3_TO_SHUABAO_TRANSFER_MAP.md:38-41`
6. **吞噬丹**：背包空位 ≤1 触发紧急管线；先背包用（`pill_bag`），没有则扫黑市买（`pill_market`）+ Z 拾取；找丹时顺手买宝物刷新（不拾取）。`[脚本3] main_dis.txt:54552-54903`
7. **局内主循环**（`ViLDA5FwlExa2P5EP6j.Run`）：24 分钟硬顶；每轮 G 技能→英雄→V 宝物→G→F 羁绊→G→主线开关→武器→V 龙珠，每步之间查「提前挑战」。`[反编译] ViLDA5FwlExa2P5EP6j.cs:29-114`
8. **按键映射**：F=羁绊面板、G=技能面板、V=宝物/龙珠、H=刷新、Z=关闭/确认、Q/W/E=神器三槽；**B 键不在 PressKey 映射中**。PressKey 后固定 `Sleep(500ms)`。`[反编译] AutoJob.cs:84-239`
9. **F4/F1 走 OSK 屏幕键盘**（Function Mode→F4/F1），非直接按键；F4 在检测到 5-6~5-10 关卡且 `AutoCloseMainLine` 时触发关主线。`[反编译] AutoJob.cs:378-467`
10. **配置键分两套默认值**：`Settings.cs` 代码默认（如 `QueryTimeOut=200`、`CJBBoss="15猛虎之神"`）与 `GameScript.exe.config` 覆盖值（`QueryTimeOut=60`、`CJBBoss=""`）不一致，以 config 为运行时生效值。`[配置] Settings.cs:24,42,303; GameScript.exe.config:10-48`

---

## 2. 五个主题表格

### ① 羁绊/卡组

| 结论 | 证据 | 我方可用范围 |
|---|---|---|
| **预设卡组 = 10 个物种**：`dasheng`(大圣) / `jingji`(经济) / `minjie`(成长·敏捷) / `zhili`(成长·智力) / `liliang`(成长·力量) / `gushou`(固守) / `baoji`(暴击) / `yihuo`(异火) / `jianshu`(箭术) / `fashu`(法术) | `[反编译] Skill.cs:46-101` `GetAllCardGroups()` | **可直接抄**作词典/分类枚举；具体卡名链须真机核对 |
| **拿卡优先级 = `Settings.Cards` 列表下标**（`IndexOf`），用户在 UI 勾选/排序 | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:131,211,246,281,391,443,495,546,609` | **可直接抄**语义（有序列表=优先级）；默认顺序须按我方策略定 |
| **进化链 `NextCardGroup`**：如固守链 `tishu×3→zhanshu×2→{shengming×3→xueshi×3→xuemo×3, gushou×2→xianzhen×2}`；暴击链 `baoji×2→zhiming×2→dapao×2`；经济链 `jj×3→{tanlan×3, tz×3}`；异火链 `yihuo` 单卡×8 级 | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:129-347` | **只作线索**：链结构可参考，具体卡名/张数须真机验证 |
| **成长链**（zhili/liliang/minjie 共享 `chengzhang` 起点）：`chengzhang×4→mingjie/liemoren/gongshen→zhili×4→mfs×4→fs×3→yanmiezhe×3` 等 | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:349-529` `IQYU9FyLKQ()` | **只作线索** |
| **大圣链**：`dasheng×1→dashengcanqu×6→dashengtaozhuang×5→{shenfa,qiji,shufa,genji,gunfa}×3`；大圣合并 5 次后切体术+暴击 | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:67-127,854-862` | **只作线索** |
| **两层名字处理：竞品不读卡头**。只模板匹配**卡名**图（`Images` 列表），点击成功从 `Images` 移除；进度 = `Images` 剩余张数，不解析「祝福(2/3)」。卡头「祝福」对应 `SpeiceName="zhufu"`（祝福×3 作为兜底组） | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:531-542,823-871` | **可直接抄**「只认卡名、不认卡头」思路；我方若要读卡头进度须另做 OCR |
| **脚本3 两层命名**：目录 `good_cards/序号_卡头_张数/`（如 `1_祝福_3`、`2_成长_4`、`36_固守_2`），文件 `1.bmp` 是卡名图；`good2_cards` 为第二套图库 | `[脚本3] COMP3_ASSET_CATALOG.csv:58-91; main_dis.txt:432-478` | **可直接抄**目录命名规范；**只作线索**具体模板 |
| **放弃/刷新条件**：面板内找不到目标卡→点 `cardRefresh` 刷新，最多 **8 次**；超限日志「刷新次数超过8次」退出；`giveUp` 按钮兜底 | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:943-962; AutoJob.cs:120` (`giveUp` 资源) | **可直接抄**「有界刷新+超限退出」；次数 8 须真机标定 |
| **推进阈值**：卡槽数 = `10 - 已占`（`NZl88hnTMe`）；≥9 张先吃丹药腾位；无丹药跳出先选宝物再来 | `[反编译] AutoJob.cs:546-550; H9w4YXUwUCCOSsJMsLL.cs:914-925` | **可直接抄**语义；阈值 9/10 须真机标定 |
| **面板开合**：`PressKey("f")` 开羁绊；`card_hide` 模板关面板，失败点固定区 `kpOfuTuhN` 兜底 | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:928; AutoJob.cs:280-302` | **只作线索**：固定区兜底与我方 fail-closed 冲突 |
| **可关羁绊**：`AutoCard=False` 时主循环跳过羁绊步骤（「关闭羁绊 & 升级武器」产品开关） | `[反编译] ViLDA5FwlExa2P5EP6j.cs:60-67; 简单介绍.html:518-520` | **可直接抄**开关粒度 |
| **技能卡组与羁绊分离**：`Skills` 配置（如 `jq,pg`）选主动技能；`ASJJSFirst`/`SanlingFirst` 等布尔控制进化分支顺序；互斥卡 `rgQ8nCUqVb` 在卡头上方 ROI 判色（金/紫/蓝/绿）决定是否点互斥 | `[反编译] WCHYKk8aDMJ1mnj1LTP.cs:132-257,352-449` | **只作线索**：色环判定脆，须真机验证 |
| **奥数增伤**：开启后优先拿「奥数激光→瓦解光线，奥数射线→焦点」四张卡 | `[包面] 简单介绍.html:513-515; [反编译] WCHYKk8aDMJ1mnj1LTP.cs:237-243` | **只作线索** |
| **脚本3 羁绊默认锁**：`DEFAULT_SYNERGY_LOCKS_BY_BUILD` 按物理/法系预设锁链（如物理=成长:棍法,根基,身法,奇技,术法 / 力量:收割者 …） | `[脚本3] main_dis.txt:535-541` | **可直接抄**「按 build 预设锁链」产品思路 |
| **与顶尖玩家行为样本对照**：视频研究 205 次刷新/拒卡（`refusals.csv`/`events.csv`，n=205，面板出现可信/选中不可信）；9 条套装 need 提案已入库。可用来校准「何时刷新/拒哪些散卡」的行为先验，**不得**把 `picks.csv` 当选卡真值 | `[实机GT] video_policy/README.md:3-5; VIDEO_LINE_CLOSEOUT_20260920.md:16-21` | **只作线索**（行为先验，非竞品逻辑） |
| **与我方攻略策略包对照**：竞品 `Cards` 有序列表（用户勾选物种）≈ 我方 `official_strategy_defaults.json` 的 `bond_priority`（round1_must=祝福/成长/经济/贪婪/挑战 → attr_chain → round3_survival → must_take 急速 → round4_optional）；竞品 `NextCardGroup` 进化链 ≈ 我方 `attr_routes.chain`（门卡4→中环4→次环3→UR3，约1400木/链）。我方侧为**攻略+KB，非新实机** | `[竞品] Settings.cs:737-749; H9w4YXUwUCCOSsJMsLL.cs:668-787` vs `[我方] config/official_strategy_defaults.json:135-147,59-61` | **可直接抄**对照结论；具体顺序以我方策略包为准 |

### ② 宝物

| 结论 | 证据 | 我方可用范围 |
|---|---|---|
| **默认优先列表**（`LongzhuJob.XTkc6dtk7E`）：`longzhu, longzhu2, chongnengzhanchui, bbx, shuaxinquan3, kfds, baowushuaxin, hide`（按序匹配，命中即点） | `[反编译] LongzhuJob.cs:16-26` | **可直接抄**白名单思路；具体卡名须真机核对 |
| **DevelopPriority 优先列表**（`Bjqc7Eg8N2`，发育优先时用）：`yishenshenzhuang, onepiece, manjidalao, shencimucai, bolidapao, bbx, chongnengzhanchui, shuaxinquan3, fengwuzhe, manwuzhe, yinwuzhe, yazhi, gongjian, shadililiang, shadiminjie, shadizhili, tiaozhanshashou, jingyingshashou, lingzhushashou` | `[反编译] LongzhuJob.cs:28-49` | **只作线索** |
| **宝物三选一列表**（`Q4Qf1OB0kqbcIxuImlQ`）：默认 `[treasureRefreshGift, treasurechest]`；DevelopPriority 时 `[sword, 2000baowu, treasurechest, treasureRefreshGift, woodgift]`；全量含 `danGif, skillRefreshGift, heroRefresh` | `[反编译] Q4Qf1OB0kqbcIxuImlQ.cs:42-57` | **可直接抄**「按模式切列表」 |
| **负面宝物处理：竞品1 无禁拿名单、无红字判定**。只有正向白名单 + 找不到就 `giveUp`。`giveUp` 按钮资源存在，但不是「识别负面后放弃」，是「无目标时放弃」 | `[反编译] LongzhuJob.cs:82; Q4Qf1OB0kqbcIxuImlQ.cs` 无负面逻辑；`[包面]` Images 有 `giveUp.png` | **必须拒绝**「竞品有负面禁拿」这一假设；负面策略须我方自建 |
| **与我方实机 GT 对照**：我方 96 卡目录（`treasure_debuff_frames/treasure_catalog.md`）已标负面 19 / 存疑 2；竞品1 零对应物。若要抄竞品白名单，须与我方负面名单做差集，**不得**用竞品列表覆盖我方禁拿 | `[实机GT] treasure_debuff_frames/report.md:6-38` | **只作对照**，不抄竞品列表 |
| **刷新怎么花**：`PressKey("h")` 刷新，最多 **5 次**（`num2=5` 起）；`noSkillNum` 模板出现则提前停；刷新前保留目标列表，命中即移除 | `[反编译] Q4Qf1OB0kqbcIxuImlQ.cs:86-138` | **可直接抄**「有界刷新」；次数 5 须真机标定 |
| **宝物配置位**（说明书）：「买了宝物的大佬设置为 6，没买的就是 7」——对应 `TreasureNum`（代码默认 3） | `[包面] 简单介绍.html:535-536; [配置] Settings.cs:821-833` | **只作线索**：语义是「目标宝物槽位数/已购数」，须真机确认 |
| **脚本3 宝物刷新耗尽**：`is_treasure_no_refresh_by_color@5994` 红像素(185,16,13)±16≥101 判耗尽→点放弃；单面板刷新保护上限 12 次 | `[脚本3] COMP3_TO_SHUABAO_TRANSFER_MAP.md:35; main_dis.txt:60041-60049` | **可直接抄**「红字耗尽→放弃」信号；ROI/阈值须真机标定 |
| **脚本3 宝物刷新不计次数**：「刷新不计次数；每次最终『放弃』才消耗 1 次宝物」 | `[脚本3] main_dis.txt:84123` | **可直接抄**计数语义 |
| **龙珠≥6 才进宝物流程**（`DragonBallCount>=6`）；龙珠≥6 且见 `cundang` 按钮→点存档 | `[反编译] ViLDA5FwlExa2P5EP6j.cs:47-54; LongzhuJob.cs:122-160` | **只作线索**（战后链，已在既有文档覆盖） |

### ③ 黑商

| 结论 | 证据 | 我方可用范围 |
|---|---|---|
| **脚本1 反编译无「黑商/黑市/吞噬丹」显式逻辑**（全库 grep `黑商|吞噬|merchant|shop` 零命中业务代码） | `[反编译] 全源码 grep` | **推断**：脚本1 的「买宝物刷新」可能并入龙珠/宝物列表（`baowushuaxin` 模板），无独立黑商 FSM |
| **脚本3 黑市 = `MARKET_GOODS_ZONE(1534,529,1764,571)`**，买两类：「宝物刷新次数」（`baowushuaxin`）和「吞噬丹」（`pill_market`） | `[脚本3] main_dis.txt:937,54552-55287; COMP3_TO_SHUABAO_TRANSFER_MAP.md:38-40` | **可直接抄**区域+两类商品模型；坐标须真机标定 |
| **买什么**：① 宝物刷新次数（主目标，空档预购+存档前补购）；② 吞噬丹（背包危险时）；③ 找丹时顺手买宝物刷新（不拾取） | `[脚本3] main_dis.txt:54637-54658,55514-55543,69589-69595` | **可直接抄**优先级与「顺手买不拾取」 |
| **什么时候买**：① 战斗空档 `idle_prebuy_baowushuaxin_once`（最低优先级，一步后立即复查技能）；② 背包空位≤1 触发吞噬丹管线；③ 存档倒计时宝物阶段最终补购 | `[脚本3] main_dis.txt:55514,58664-58695,69589-69595` | **可直接抄**触发时机模型 |
| **吞噬丹用法**：背包危险（`empty` 空位≤1）→ 先 `pill_bag` 背包内直接用 → 没有则扫黑市 `pill_market` 买+Z 拾取→再用；复查背包未见→继续尝试 | `[脚本3] main_dis.txt:54552-54903; COMP3_TO_SHUABAO_TRANSFER_MAP.md:39-41` | **可直接抄**管线顺序；空位阈值 ≤1 须真机标定 |
| **资源阈值 / 停止条件**：① 同一商品同位 **3 连点仍在** = 购买资源不足，停；② H 刷新前后像素 **2 次无变化** → 10s 冷却（非判死）；③ 采样故障返回 999=永远算「有变化」防误判 | `[脚本3] COMP3_TO_SHUABAO_TRANSFER_MAP.md:38,72; main_dis.txt:55009,55108,54801` | **可直接抄**「正向停止+冷却」；与我方 merchant 20 reroll 对比见借鉴清单 |
| **H 刷新黑市**：`黑市刷新H` / `刷新黑市H-找吞噬丹` / `黑市刷新H-找宝物刷新次数` | `[脚本3] main_dis.txt:4995,54766,55179` | **可直接抄** |
| **禁买规则**：空位≤1 时「禁买非清包牌」 | `[脚本3] COMP3_TO_SHUABAO_TRANSFER_MAP.md:41` | **可直接抄**「满仓只买清包」 |
| **与玩家行为样本对照**：视频研究未直接覆盖黑商资源阈值（n=0 条黑市购买事件）；205 次拒卡/刷新可侧面反映「木材紧张时的止损」行为，但不构成黑商阈值证据 | `[实机GT] video_policy/refusals.csv`（205 行）；黑市事件 0 | **只作线索**，阈值仍须实机标定 |

### ④ 局内调度节拍

| 结论 | 证据 | 我方可用范围 |
|---|---|---|
| **主循环硬顶 24 分钟**（`AddMinutes(24.0)`），到时或见「提前挑战/继续游戏」即退出进入下一阶段 | `[反编译] ViLDA5FwlExa2P5EP6j.cs:32-39` | **可直接抄**硬顶概念；24min 须真机标定 |
| **每轮固定序列**：G 技能 → 英雄选择 → V 宝物（`DragonBallCount≥6`）→ G → F 羁绊（`AutoCard`）→ G → 主线开关（`vr38R0dXim(true)` 点自动）→ 武器（`AutoWeapon`）→ V 龙珠（`DevelopPriority\|\|FindLongzhuInGame`）；每步间查 `AqoBD5r8RG`（提前挑战/发育完成/继续游戏） | `[反编译] ViLDA5FwlExa2P5EP6j.cs:39-93` | **可直接抄**序列骨架；顺序可按我方 C2/FSM 重排 |
| **按键映射**（`PressKey`）：`f`=羁绊面板、`g`=技能面板、`v`=宝物/龙珠、`h`=刷新、`z`=关闭/确认、`q/w/e`=神器三槽、`s`=（映射存在）、`enter`=确认、`-`=（映射存在）；**`b` 不在映射**（`throw ArgumentException`） | `[反编译] AutoJob.cs:84-239` | **只作线索**：键位是竞品契约，我方键位须按我方 scenes.json |
| **PressKey 固定 `Sleep(500ms)`** | `[反编译] AutoJob.cs:215` | **只作线索** |
| **F4 关主线**：`AutoCloseMainLine` 开启时，检测到关卡 `5-6/5-7/5-8/5-9/5-10` 模板 → `vr38R0dXim(false)` 走 OSK Function Mode→F4；`CloseMainLineTime` 秒后也可关 | `[反编译] AutoJob.cs:416-467,360-376; 简单介绍.html:501-503` | **可直接抄**「过 5-5 自动清怪关主线」语义；OSK 依赖**必须拒绝** |
| **F1 集火**：`jihuo` 图标（1250,795,1310,860）未找到 → OSK Function Mode→F1 | `[反编译] AutoJob.cs:407-414` | **只作线索** |
| **提前挑战**：`tqtz` 模板命中 → `DevelopTime==0` 直接触发；声望模式且非慢刷也直接；否则等 `DevelopTime` 秒后触发；触发后点 `yes` 确认（`QueryTimeOut` 超时） | `[反编译] AutoJob.cs:328-358; ViLDA5FwlExa2P5EP6j.cs:96-103` | **可直接抄**「发育完成→提前挑战」；默认 `DevelopTime=0`（立刻） |
| **发育时间分段**（说明书）：快刷 0 / 慢刷按实力 / 刷满 24min→设 1500 | `[包面] 必读.html:648-654` | **可直接抄**用户心智文案 |
| **神器释放节拍**：提前挑战后 `Sleep(ArtifactDelay×1000)`，再按固定 LTRB 三槽各点一次+F1 集火 | `[反编译] ViLDA5FwlExa2P5EP6j.cs:104-113` | **必须拒绝**固定 LTRB 盲点（我方用槽位证据） |
| **清理节拍**：`AutoCleanInterval`（默认 5）——每 N 个 `CycleNum` 循环做一次分解装备/合成宝石 | `[反编译] IitdC7cGjabhsQ6mwpH.cs:158; Settings.cs:513-525` | **可直接抄**「按局数间隔清理」 |
| **关卡选择间隔** `StageSelectInterval` 默认 500ms；**鼠标操作间隔** `MouseOperationInterval` 默认 50ms | `[配置] Settings.cs:989-1001,1031-1043` | **可直接抄**量级 |
| **脚本3 节拍**：`SKILL_PANEL_STABILIZE_WAIT=0.2s`、`CRITICAL_CLICK_PRE/POST_WAIT=0.2s`、`KK_START_RECHECK_WAIT=5.0s`、`QUEST_RESUME_DELAY_DEFAULT=60s`、`DM_COMPAT_INTERVAL_SECONDS=0.6s`；技能面板 5 次放弃未关→5s 冷却仍保持总门禁 | `[脚本3] main_dis.txt:517-533,54076; COMP3_TO_SHUABAO_TRANSFER_MAP.md:88` | **可直接抄**「5 次放弃→冷却但不刷活性时钟」（对比我方 R1） |
| **脚本3 ONE ACTION THEN RESCAN**：技能一步/羁绊一步/黑市预购一步后强制回顶重评 | `[脚本3] COMP3_TO_SHUABAO_TRANSFER_MAP.md:96` | **可直接抄**（我方 tick 级已有，多 tick step-gate 可对齐） |
| **挑战开关**：「提前挑战」按钮（`tqtz`）是唯一显式挑战开关；邪修秘境模式「其他功能无效、只自动化 Boss」 | `[反编译] AutoJob.cs:330; [包面] 简单介绍.html:457-459` | **可直接抄**模式隔离 |

### ⑤ 相关配置键和默认值

> 两套默认：`Settings.cs` 代码初值 vs `GameScript.exe.config` 覆盖值。运行时以 config 为准（`JsonSettingsBase`）。「局内决策」相关键如下；战后/Boss 键仅列名不展开（见既有文档）。

| 配置键 | 代码默认 (Settings.cs) | config 默认 (1.6.2) | 语义 | 证据 | 我方可用范围 |
|---|---|---|---|---|---|
| `Skills` | `List{}` | `"jq,pg"` | 主动技能有序列表（jq=剑气, pg=普攻） | `[配置] Settings.cs:373-385; config:34-36` | **可直接抄**语义 |
| `Cards` | `List{}` | — | 羁绊物种有序列表=优先级 | `[配置] Settings.cs:737-749` | **可直接抄** |
| `AutoCard` | `true` | — | 自动羁绊开关 | `[配置] Settings.cs:695-707` | **可直接抄** |
| `AutoWeapon` | `true` | — | 自动武器升级开关 | `[配置] Settings.cs:709-721` | **可直接抄** |
| `AutoCloseMainLine` | `false` | — | 过 5-5 自动关主线 | `[配置] Settings.cs:499-511` | **可直接抄** |
| `CloseMainLineTime` | `0` | — | 游戏开始 N 秒后关主线（0=按关卡触发） | `[配置] Settings.cs:863-875` | **可直接抄** |
| `DevelopTime` | `0` | — | 发育秒数；0=立刻提前挑战；1500=24min | `[配置] Settings.cs:779-791; 必读.html:648-654` | **可直接抄**语义 |
| `DevelopPriority` | `false` | — | 发育优先（切宝物/龙珠列表） | `[配置] Settings.cs:877-889` | **可直接抄** |
| `AutoCleanInterval` | `5` | — | 每 N 循环清理一次 | `[配置] Settings.cs:513-525` | **可直接抄** |
| `TreasureNum` | `3` | — | 宝物目标数/槽位（说明书 6/7） | `[配置] Settings.cs:821-833; 简单介绍.html:535-536` | **只作线索** |
| `CycleNum` | `99` | — | 局内循环上限 | `[配置] Settings.cs:793-805` | **只作线索** |
| `QueryTimeOut` | `200` | `60` | 等待/查询超时秒（说明书建议 200） | `[配置] Settings.cs:303-315; config:19-21; 必读.html:635-640` | **可直接抄**语义；默认值以我方标定为准 |
| `GameTimeOut` | `15` | `15` | 单局超时（分钟？） | `[配置] Settings.cs:485-497; config:46-48` | **只作线索** |
| `DragonBallCount` | `7` | `7` | 龙珠目标数（≥6 触发宝物/存档） | `[配置] Settings.cs:317-329; config:22-24` | **只作线索** |
| `StageSelectInterval` | `500` | — | 关卡选择间隔 ms | `[配置] Settings.cs:1031-1043` | **可直接抄**量级 |
| `MouseOperationInterval` | `50` | — | 鼠标操作间隔 ms | `[配置] Settings.cs:989-1001` | **可直接抄**量级 |
| `ArtifactMode` | `3` | — | 神器槽释放数 1/2/3 | `[配置] Settings.cs:1241-1253` | 已覆盖，列名 |
| `ArtifactDelay` | `0` | — | 神器释放延迟秒 | `[配置] Settings.cs:1199-1211` | 已覆盖，列名 |
| `ArchiveBossTime` | `120` | — | 存档挑战总预算秒 | `[配置] Settings.cs:807-819` | 已覆盖，列名 |
| `ASJJSFirst` | `true` | — | 奥数箭进化优先 | `[配置] Settings.cs:1325-1337` | **可直接抄** |
| `SanlingFirst` | `false` | — | 散灵冰箭优先 | `[配置] Settings.cs:1045-1057` | **只作线索** |
| `SwordIncreasedDamaged` | `false` | — | 剑士增幅技能组 | `[配置] Settings.cs:1003-1015` | **可直接抄** |
| `Electrify` | `false` | — | 感电/电网技能组 | `[配置] Settings.cs:1017-1029` | **可直接抄** |
| `ChainIncreasedDamaged` | `false` | — | 闪电链技能组 | `[配置] Settings.cs:1087-1099` | **可直接抄** |
| `ICEIncreasedDamaged` | `false` | — | 冰霜技能组 | `[配置] Settings.cs:1101-1113` | **可直接抄** |
| `HQIncreasedDamaged` | `false` | — | 火球技能组 | `[配置] Settings.cs:1115-1127` | **可直接抄** |
| `SXIncreasedDamaged` | `false` | — | 射线/激光技能组 | `[配置] Settings.cs:1129-1141` | **可直接抄** |
| `JGIncreasedDamaged` | `false` | — | 激光技能组 | `[配置] Settings.cs:1143-1155` | **可直接抄** |
| `DZIncreasedDamaged` | `false` | — | 地震技能组 | `[配置] Settings.cs:1283-1295` | **可直接抄** |
| `SingleSelectedSkill` | `""` | — | 单选技能模板名 | `[配置] Settings.cs:1269-1281` | **只作线索** |
| `EvilTreasureMode` | `0` | — | 邪修宝物模式 | `[配置] Settings.cs:1185-1197` | **只作线索** |
| `AutoGamblingTime` | `270` | — | 赌木超时秒 | `[配置] Settings.cs:835-847` | **只作线索** |
| `BoosLiveTime` | `0` | — | 邪修 Boss 存活秒 | `[配置] Settings.cs:751-763` | **只作线索** |
| `KillBossNum` | `600` | — | 邪修杀 Boss 数 | `[配置] Settings.cs:765-777` | **只作线索** |
| `RoomTimedOutAndExited` | `60` | — | 房间超时退出秒 | `[配置] Settings.cs:1213-1225` | **只作线索** |
| `NumberOfScroll` | `1` | — | Boss 列表滚动次数 | `[配置] Settings.cs:975-987` | 已覆盖，列名 |
| `GameMode` | `0` | `0` | 0=独狼 2=带队 3=蹭车 5=多开？ | `[配置] Settings.cs:471-483; config:43-45` | **只作线索**（枚举须真机确认） |
| `AutoSecretRealm` | `false` | `False` | 自动秘境 | `[配置] Settings.cs:331-343` | 已覆盖，列名 |
| `FindLongzhuInGame` | `true` | — | 局内找龙珠 | `[配置] Settings.cs:1073-1085` | **只作线索** |
| `FollowTheLead` | `true` | — | 跟车 | `[配置] Settings.cs:1227-1239` | **只作线索** |
| `HasMainForce` | `true` | — | 有主力 | `[配置] Settings.cs:947-959` | **只作线索** |
| `NeedSelectBoss` | `true` | — | 需选 Boss | `[配置] Settings.cs:961-973` | **只作线索** |
| `MoveWindow` | `true` | — | 移动窗口 | `[配置] Settings.cs:1059-1071` | **只作线索** |
| `LegacyMode` | `false` | — | 旧模式 | `[配置] Settings.cs:1157-1169` | **只作线索** |
| `ContinueMiJing` / `ContinueReputation` | `false` | — | 秘境/声望续局 | `[配置] Settings.cs:1311-1323,849-861` | **只作线索** |
| `ReputationEffect` | `false` | — | 声望慢刷（影响提前挑战） | `[配置] Settings.cs:1255-1267` | **只作线索** |
| 脚本3 常量 | — | — | `MARKET_GOODS_ZONE(1534,529,1764,571)`、`INVENTORY_ZONE(1455,602,1556,758)`、`SKILL_PANEL_STABILIZE_WAIT=0.2`、`DM_CARD_CONFIDENCE=0.9`、`DM_SKILL_CONFIDENCE=0.88→0.8`、`DM_COMPAT_INTERVAL_SECONDS=0.6` | `[脚本3] main_dis.txt:517-533,933-937; COMP3_TO_SHUABAO_TRANSFER_MAP.md:29` | **只作线索**（ROI/阈值须真机标定） |
| 我方策略包对照 | — | — | `official_strategy_defaults.json`：`builds[].skills`/`cards`（短码）、`bond_priority.round1_must`、`attr_routes.chain`（gate_need=4，1400木/链）、`bond_trees`（round1-4 解锁树）。竞品 `Skills`/`Cards` 短码语义与之同构，但我方侧为**攻略+KB，非新实机** | `[我方] config/official_strategy_defaults.json:3-147` | **可直接抄**字段对齐；默认值以我方策略包为准 |

---

## 3. 可借鉴清单（按价值排序）

| 序 | 借鉴点 | 来源 | 价值 | 落地建议 |
|---|---|---|---|---|
| 1 | **黑市「正向停止」**：同位 3 连点仍在=资源不足停；2 次像素无变化→冷却非判死 | `[脚本3] COMP3_TO_SHUABAO_TRANSFER_MAP.md:38,72` | 高 | 补我方 merchant 正向停止（对比 R4 fail-open）；走 C2+冻结回放 |
| 2 | **吞噬丹紧急管线**：空位≤1→背包用→黑市买→Z 拾取→复查；找丹顺手买宝物刷新 | `[脚本3] main_dis.txt:54552-54903` | 高 | 我方清包/满仓策略可对齐；须真机 GT |
| 3 | **羁绊「物种链」模型**：`CardGroup{SpeiceName, Images[], NextCardGroup, Priority}` + 用户有序列表=优先级 | `[反编译] CardGroup.cs; H9w4YXUwUCCOSsJMsLL.cs:668-787` | 高 | 我方 choice_policy 可加「进化链」维度；词典对齐 |
| 4 | **只认卡名不认卡头** + 目录编码卡头（`序号_卡头_张数/`） | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:823-871; [脚本3] COMP3_ASSET_CATALOG.csv:66` | 高 | 我方两层名字处理：卡名模板匹配 + 卡头做分类元数据；不 OCR「(2/3)」除非用户要进度 |
| 5 | **有界刷新+超限退出**：羁绊 8 次 / 宝物 5 次（脚本3 12 次保护）/ 黑市 2 次无变化→10s 冷却 | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:958; Q4Qf1OB0kqbcIxuImlQ.cs:86; [脚本3] COMP3_TO_SHUABAO_TRANSFER_MAP.md:100` | 高 | 我方 merchant ≤20 reroll 可收束到「有界+冷却」 |
| 6 | **宝物刷新耗尽红像素信号** | `[脚本3] COMP3_TO_SHUABAO_TRANSFER_MAP.md:35` | 中 | 我方 treasure 刷新耗尽判定可加红字双证据 |
| 7 | **「刷新不计次数，放弃才消耗」**计数语义 | `[脚本3] main_dis.txt:84123` | 中 | 对齐我方用户规则「存档中间四个每天 8 次也全点」 |
| 8 | **按 build 预设羁绊锁链**（物理/法系） | `[脚本3] main_dis.txt:535-541` | 中 | 我方可加「流派预设」配置 |
| 9 | **5 次放弃→5s 冷却但不刷活性时钟** | `[脚本3] COMP3_TO_SHUABAO_TRANSFER_MAP.md:88,123` | 中 | 修我方 R1（panel 检疫饿死 idle watchdog） |
| 10 | **失败即截图**（`CaptureWin("noBoss"|"cjb_fail"|...)`） | `[反编译] AutoJob.cs:266-278` | 中 | 我方 incident 默认动作对齐 |
| 11 | **发育时间/存档挑战时间/等待时间三参数向用户说清** | `[包面] 必读.html:625-662` | 中 | 看板文案对齐用户心智 |
| 12 | **技能增伤组开关**（剑士/感电/冰霜/火球/地震/射线/激光 各一组模板） | `[反编译] WCHYKk8aDMJ1mnj1LTP.cs:145-189` | 中 | 我方 skill 分组配置可参考 |
| 13 | **模式隔离**（邪修秘境「其他功能无效」） | `[包面] 简单介绍.html:457-459` | 中 | 我方 hitch/solo/reputation 已分模式，可再收束 UI |
| 14 | **互斥卡色环判定**（金/紫/蓝/绿 BGR 均值距离） | `[反编译] WCHYKk8aDMJ1mnj1LTP.cs:132-138,428-449` | 低 | 仅线索；色环脆，须真机 |
| 15 | **卡槽≥9 先吃丹药腾位** | `[反编译] H9w4YXUwUCCOSsJMsLL.cs:914-925` | 低 | 仅线索 |

---

## 4. 需要实机验证的清单

| 序 | 待验证项 | 为什么要验 | 最小证据包 |
|---|---|---|---|
| 1 | 羁绊卡名模板与进化链张数 | 反编译链结构可能与 1.6.2 有版本差 | 羁绊面板连续帧（含卡名+卡头），每条链至少 1 帧/级 |
| 2 | 卡头「祝福(2/3)」像素与卡名「智力祝福」同屏关系 | 确认「不读卡头」是否在新 UI 仍成立 | 同一帧含卡头+卡名 |
| 3 | 刷新上限 8 次 / 宝物 5 次 / 黑市 2 次冷却 | 阈值是代码常量还是配置 | 实机日志/录屏计数 |
| 4 | 黑市 ROI 与「宝物刷新次数/吞噬丹」模板 | 脚本3 坐标是 1366×768 基准 | 黑市面板帧 + 商品区特写 |
| 5 | 吞噬丹触发阈值（空位≤1） | 代码常量 | 背包空位 0/1/2 各一帧 |
| 6 | 宝物刷新耗尽红像素 ROI/阈值 | 脚本3 红像素参数是另一套分辨率 | 刷新耗尽面板帧 |
| 7 | F/G/V/B/F4/挑战开关的真实键位 | 竞品键位 ≠ 我方键位；B 键竞品未映射 | 我方 scenes.json + 实机按键记录 |
| 8 | `GameMode` 枚举语义（0/2/3/5） | 推断不完整 | UI 模式切换帧 + 日志 |
| 9 | `TreasureNum` 6/7 语义 | 说明书与代码默认 3 不一致 | 看板 UI + 实机行为 |
| 10 | 互斥卡色环四色阈值 | 色环对渲染敏感 | 不同品质互斥卡各 1 帧 |
| 11 | 负面宝物：竞品是否在 1.6.2 新增禁拿 | 落库反编译可能是旧版 | 1.6.2 主程序字符串/资源对比（**不做新反编译**，仅包面 grep） |
| 12 | 24 分钟硬顶是否仍是现行值 | 反编译版本差 | 实机长跑日志 |

---

## 5. 明确未证实清单（禁止推断）

- 竞品 1.6.2 是否新增了负面宝物禁拿 / 红字判定（落库反编译无，包面无对应资源名）。
- `GameMode` 完整枚举与各模式差异。
- `B` 键在竞品中的用途（`PressKey` 不支持；可能走其他输入路径）。
- 脚本3 黑市 ROI 是否适用于 1600×900（脚本3 是 1366×768 基准）。
- 羁绊进化链的卡名中文对照（反编译只有拼音 key，如 `tishu`→体术？须真机卡面确认）。
- 「祝福(2/3)」的 (2/3) 是否为「已收集/总需」——竞品不读，我方须实机确认语义。

---

*本文全部为竞品静态观察 + 脚本3 字节码/分析报告引用 + 我方实机 GT 路径引用。无合成帧。待我方 capture、帧证据与回放断言前，不得将本文阈值/坐标/键位接入运行逻辑。*
