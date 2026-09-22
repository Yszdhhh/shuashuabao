# 单人局内机制事实表（SOLO_MECHANICS_FACTS）

- **交付日期**：2026-09-22
- **分析目录**：`G:\刷刷宝\_facts_20260922\mechanics_solo\`
- **代码/主目录**：只读；未写 `GameScript-Local`、未跑 pytest/release_gate、未发游戏输入、未改 GATE_BASELINE、未 push
- **可复跑脚本**：`scripts/peek_trace_schema.py`、`scripts/analyze_solo_mechanics.py`、`scripts/extract_ocr_panels.py`；输出在 `out/`

## 证据等级与样本量总表

| 等级 | 含义 | 本表主要来源 | 样本量 n |
|---|---|---|---|
| **实机GT** | bundle+帧/事件 id，实机录到状态变化 | `G:\刷刷宝\captures\hitch_lobby_chain_20260922_004851_422384`（主证据，trace 4147 行，frames 3624，incidents panels）+ `C:\tmp\shuabao-captures\hitch_lobby_chain_*`（25 包，15 包有局内段） | 局内段 **n=45**（主包 **n=10**）；宝物三选面板 **n=688**（主包 134 + C-tmp 554） |
| **实机帧/卡面** | LIVE_BUNDLE：帧上游戏文字，无动作前后对照 | 同上 + `docs/mechanics-contract-20260917:evidence/` + `fixtures/` | 见各节 |
| **视频OCR** | 录屏抽帧，强于口述、弱于实机 | `G:\刷刷宝\_facts_20260919\video_policy\`（BV1bobN66EUN / BV1gRYr6pEQv / BV1nmTR65Eoq 等） | 面板事件 **n=1075**；EX 出现 **n=94**；拒卡/刷新 **n=205**；关闭快照 **n=435** |
| **仓库代码** | file:line，表示“现在怎么写”，**不是机制证据** | `GameScript-Local` 只读 | 见 §6 |
| **KB/合成** | 已有研究引用不重证 | `docs/reviews/evidence_20260916/solo_orchestration/KB_MECHANICS_SYNTHESIS.md`（下称 **KB综述**）；`docs/mechanics-contract-20260917:MECHANICS_CONTRACT_RESEARCH_20260917.md`（下称 **09-17合同**） | KB综述 G1–G3 **n=3**；09-17 合同 4 包 |
| **攻略/竞品** | 仅旁证 | 攻略参考截图；竞品 1.6.2 | 不作机制真值 |
| **推断** | 明确写推导链 | — | — |

**禁止项已遵守**：未使用 `%TEMP%\shuabao-captures\solo_ingame_chain_*`（未进局内）；未合成帧冒充实机。

**主证据包结论（manifest.metrics）**：`rounds_started=9`（s0.game_count 最终=10）、`victory_count=6`、`failure_count=4`、`merchant_devour_acquired=44`、`talisman_acquired=48`；自然 E2E 以 `production input on UNKNOWN` 收尾（exit button timeout），**局内段仍有效**。

---

## ① 局内时间线（开局 → 5-5/5-6/6-1 → Boss → 结束）

### 1.1 局内段时长分布（实机GT，trace `phase_after=MAIN_LINE` 连续段）

| 统计 | 全样本（主+C-tmp） | 主包 hitch_20260922_004851 |
|---|---|---|
| n | **45** | **10** |
| min | 29.1 s（早退段） | 457.3 s |
| p25 | 514.9 s | 568.2 s |
| **中位数** | **589.0 s ≈ 9.8 min** | **581.1 s ≈ 9.7 min** |
| p75 | 671.0 s | 588.7 s |
| max | 1511.0 s ≈ 25.2 min | 671.0 s |
| mean | 633.7 s | 574.1 s |

脚本：`scripts/analyze_solo_mechanics.py` → `out/aggregate.json`、`out/summary_hitch_lobby_chain_20260922_004851_422384.json`。

**解读（推断）**：中位局内约 **10 分钟**就结束（胜利或超时/退出），明显短于 KB综述 G2 的 16.5 min 胜利局与 G3 的 23+ min 僵局。主包 10 局集中在 8–11 min，符合“蹭车/快速局”节奏，**不能直接外推单人 1-21 完整主线到 6-1 的时长**。

### 1.2 胜负与结束方式（实机GT）

主包 `s0.round_outcome` 变化（n=6 次记录，覆盖 game_count 0→9）：

| 结果 | 次数（outcome_changes） | manifest.metrics 全包 |
|---|---|---|
| VICTORY | 3（含开局 1 次） | victory_count=**6** |
| TIMEOUT | 3 | failure_count=**4** |

C-tmp 聚合：15 包有局内段、共 45 段；`hitch_lobby_chain_20260921_095128` 单包 **9 段**（最长连跑）。

### 1.3 主线关卡 5-5 / 5-6 / 6-1

| 观测 | 结果 | 证据 |
|---|---|---|
| 主包/C-tmp trace、events、ocr_shadow 里的 `X-Y` 关卡 token | **0 命中**（脚本 `extract_ocr_panels.py` stage_* 全空） | 实机GT（负结果） |
| KB综述 G1（1-15） | 5-6 @5:01 → **6-1 全主线完成** @7:01 | KB综述实测，n=1 |
| KB综述 G2（1-21） | **5-5** @11:00 → 提前挑战 @11:27 → 胜利 @16.5 min | KB综述实测，n=1 |
| KB综述 G3（1-21） | **4-5 停滞** 8:52–16:24；23 min 仍在 4-9，未到 5-5 | KB综述实测，n=1 |
| 09-17 合同 | 5-5=阿克蒙德，红字“难度要高于关卡最终BOSS”；为提前挑战前置 | 实机卡面+KB |
| 视频线 | `ex_ledger` 记录每张 EX 出现时的「关卡/波次」OCR（高可信） | 视频OCR n=94 出现行 |

**结论（一句话）**：局内墙钟中位约 **9.8 min**；5-5 是硬门槛（比最终 Boss 更难），5-6/6-1 只在 KB综述 G1 单样本出现，**本批 hitch 主证据未 OCR 到主线关卡号**——关卡时间线仍靠 KB n=1~3，缺口见 §7。

### 1.4 Boss / 波次（旁证）

- 一局 5 波、每 6 min 一波 Boss（KB综述顶栏倒计时，实测）。
- 主包 settings：`cjb_boss=17年兽`、`sgzx_boss=18瑟莱德丝公主`、`stage_targets` 蹭车为 `4,3,速` 前缀搜索（manifest PRECHECK settings_snapshot）。
- 挑战开关：金币/木材/经验/宝物 Challenge 各 right_click **n=10**（主包 decisions）；`EnableAutoTask` n=13。

---

## ② 木材 / 金币收入曲线；F 抽价、G/V、黑商刷新、吞噬丹

### 2.1 资源账本（KB综述 + 官方 + 实机，引用不重证）

| 资源 | 来源 | 用途/单价 | 证据 |
|---|---|---|---|
| **木材** | 开局 ~900；被动 1.5→2.4/s；主线每关 +50、Boss 关 +100；自动木材挑战；祝福 +200；贪欲钥匙 +150 | **F 抽**：20→80→**100 封顶**；羁绊三选**刷新 40**（OCR 实证） | KB综述 §1；F 价实测 G3 帧 |
| **金币** | 被动 74→104/s；祝福 +3000；贪欲金币 +6000；5-5 +100000 | 专属升级（官方）；黑市是否用金币未知 | KB综述 + `game_mechanics_kb.json` resources.gold |
| **杀敌数** | 被动 +2.5→3.5/s + 击杀 | **只用于黑商**：商品、手动刷新；吞噬丹标价 **400**（代码常量，未实机对齐单价） | KB综述；`src/shuabao/mediator.py:4291` `_MERCHANT_DEVOUR_PILL_KILL_COST = 400` |
| **技能点 G** | 每级 1 点；每抽 1 点 | G 抽技能；角标到 32 未见上限 | KB综述实测核算 |
| **V 宝物次数** | 角标=待拿次数；来自宝物挑战（推断） | V 面板三选；`刷新(N)` 另一套次数来自词条/龙珠 | KB综述 |

**总木材收入（推断，KB综述）**：HUD 被动仅 ~2.3/s，余额斜率反推 **~4.5–5.5 木/s（约 270–330/分）**，其余来自主线/挑战大额入账。与 §6 旧结论 5 一致。

**木材会下降（已修订“只涨不跌”）**：`CURRENT_STATUS_AND_HANDOFF_20260919_MECHANICS.md`：20260918_210044 13 次木材采样 **5 次下降**（总降 332、总涨 968）。

### 2.2 本批 hitch 实机动作量（实机GT，trace decisions/intents）

主包 10 局 MAIN_LINE（+全包聚合）：

| 动作 | 主包次数 | 15 包合计（约） | 说明 |
|---|---|---|---|
| BlackMerchant-refresh | **87** | ~360 | 黑商手动刷新（杀敌） |
| BlackMerchant-swallow_pill | **44** | ~180 | 吞噬丹购买/使用链路点击 |
| OpenTreasurePanel | **104** | ~550 | V 开宝物面板 |
| treasure 选择 | **44**（另有 treasure 刷新选择 18） | — | 实拿宝物 |
| giveUp 面板 | panel 名 `giveUp` **275** | — | 拒卡/放弃（含 F/G/V） |
| skill_refresh_btn | panel **221** | — | 技能刷新按钮命中 |
| PublicBackpack* | 157+79+78+41+41 | — | 蹭车公共背包存包（非单人主链） |

黑商槽位点击分布（主包）：slot0=12, slot1=8, slot2=6, slot3=11, slot4=7（5 槽货架）。

### 2.3 视频线刷新/拒卡行为样本（视频OCR，**n=205**，非实机插桩）

来源：`G:\刷刷宝\_facts_20260919\video_policy\refusals.csv` + `events.csv`（见 closeout §一.3）。

- 分布在第 1–5 波及高难度关卡；行为模式：**耗木刷新** + **放弃与主属性不匹配的散卡**。
- 只能作弱行为线索（标推断），**不能当顶尖玩家拿卡真值**（picks 强佐证仅 15/435=3.4%）。
- 与本批 hitch 的 `giveUp` 高频一致：脚本/玩家都在大量拒卡。

### 2.4 吞噬丹价格与消耗

| 项 | 值 | 证据 |
|---|---|---|
| 代码标价 | 400 杀敌 | `mediator.py:4291`（CURRENT_CODE，**未验证为机制价**） |
| 实机购买/使用点击 | 主包 swallow_pill **n=44**；manifest `merchant_devour_acquired=44` | 实机GT |
| 09-17 合同 | 984fd04 局买 11 颗丹，羁绊栏始终 ≤2–3 张，**一颗没用上** | 实机GT |
| 单价逐事件对齐 | **仍不能**从 HUD 差分反推（F 抽与刷新两笔支出夹击杀收入） | handoff 20260919 |

**结论（一句话）**：F=100/抽（1 min 后）、羁绊刷新=40 OCR 实证；木材总入约 5/s 量级但含大额脉冲；黑商只耗杀敌、吞噬丹链路本批点击充分（44），**单价仍待逐事件 HUD 对齐**。

---

## ③ 羁绊：卡头/卡名映射、(x/y) 进度、可启动卡组、启动卡与门卡

### 3.1 两层命名（结构事实，见 §6.1）

```
卡头（标题层）     = 套装/家族名 + 可选 (x/y)   例：祝福(2/3)、藏宝图(0/3)、封神
卡名（散件层）     = 图标下具体卡名            例：智力祝福、藏宝图(三)、姜子牙
```

- 生产 OCR / `mediator._fill_bond_slots_by_title_template`（`mediator.py:3179`）主要读**标题层**。
- `choice_lexicon.json` 的 `set_membership` 把两层混在同一命名空间（`_comment` 自陈）。
- 09-17 合同：1796 次实机羁绊读数，**卡名命中 0**。

### 3.2 (x/y) need 规则（多源对照）

**A. 视频双信号确认 need 提案（视频OCR，n=9，`catalog_import_proposal.json` confirmed_new）**

| 套装 | need | 进度观测 n | 激活文本 n | 首帧 |
|---|---|---|---|---|
| 五极山 | **5** | 14 | 3 | BV1bobN66EUN frame_00459_ep31 |
| 身法 | **3** | 14 | 12 | BV1nmTR65Eoq frame_00975_ep51 |
| 五行灵根 | **5** | 13 | 11 | BV1nmTR65Eoq frame_00449_ep22 |
| 肉身成圣 | **3** | 11 | 2 | BV1nmTR65Eoq frame_01329_ep74 |
| 纷争面纱 | **3** | 6 | 4 | BV1gRYr6pEQv frame_00897_ep73 |
| 点金手 | **4** | 5 | 5 | BV1gRYr6pEQv frame_00952_ep75 |
| 风之杖 | **3** | 5 | 5 | BV1gRYr6pEQv frame_00968_ep76 |
| 旋涡 | **3** | 3 | 2 | BV1nmTR65Eoq frame_01103_ep60 |
| **藏宝图** | **3** | 2 | 1 | BV1bobN66EUN frame_00010_ep1 |

与 `CURRENT_STATUS_AND_HANDOFF_20260919_MECHANICS.md` / `bond_stack_catalog.json` needs（77 条）一致方向。**可信度**：视频 OCR 强于口述、弱于本机实机；冲突不写。

**B. 视频 agree 包（与 catalog 一致，抽样）**：祝福3、法术3、箭术3、刀刀3、挑战3、成长4、贪婪3、体术3、修仙3、暴击2、战术2、智力4、敏捷4、力量4、致命2、经济3、魔术2、魔能2、大炮2 等。

**C. 实机/实验室（KB综述 + bond_stack_catalog）**：见 catalog `needs`；生命=3（Owner 20260919 确认；catalog 旧 4 与视频 conflict 行仍并存，**以 3 为准待改**）。

### 3.3 哪些卡组能真正“启动”

| 卡组 | 启动卡（卡头/卡名） | 实机是否启动 | 门卡/前置 | 终点 |
|---|---|---|---|---|
| **海盗** | 卡头 `藏宝图(0/3)` / 卡名 **藏宝图(一)(二)(三)** | 09-17：面板出现 71 次拿 0；本批 hitch 未见完整启动 GT | 集齐 3 → 置入「开进码头」开组 | UR 毁灭战舰（无 EX） |
| 封神 | `封神` / 姜子牙 | 唯一较完整推进（09-16/17） | 累计 6 张 → SSR 封神榜 | EX 圣人 |
| 刀刀 | `刀刀(0/3)` / 幽灵系带等 | 集齐→刀刀萌新（卡面） | need=3 | EX 解放的圣剑 |
| 修仙 | `修仙(0/3)` / 小绿瓶 | 集齐→练气期 | need=3 | EX 大乘期 |
| 三国 | `三国` / 乱世三国 | 开组卡面 | 3 UR 武将 → 全吞 | EX 吞食天地 |
| 亡灵 | `亡灵` / 亡灵天灾 | need=3（lab） | 100 残骸+符文 | EX 兵主 |
| 异火 | `异火` / 焚诀·黄阶 | 吞 3 → 玄阶（LIVE） | 击杀 200 吞 1 | EX 帝炎 |
| 属性门卡 | 智力/力量/敏捷 (0/4) | 完成门→次环立刻进池（KB G3） | **门卡 need=4** | 湮灭者/屠戮者/收割者 |
| 基础五组 | 祝福/成长/经济/贪婪/挑战 | 全实测可启动 | 祝福 3、成长 4、经济 3、贪婪 3、挑战 3 | 套装效果 |

**启动卡 vs 门卡**：

- **启动卡**：高级组的单张/三件套入口（藏宝图(三)、姜子牙、乱世三国、亡灵天灾、焚诀、幽灵系带…）——**无 (x/y) 或单独 need**，决定“开不开池”。
- **门卡**：属性链 `智力(0/4)/力量/敏捷`，need=4，集齐解锁中环；门卡散件本身带经济（如力量之源木材+50 并开池）。
- **EX 出现时机（视频OCR n=94，仅出现不等于选中）**：`ex_ledger.csv` 含时间戳/波次/杀敌数/同屏候选；`acquisition_reliability` 闸门：STRUCTURALLY_IMPOSSIBLE 54 / DEFAULT_FILLED 39 **不可当已入手**，CORROBORATED 仅 1。

**视频可信度边界（必须写入下游）**：

1. 「面板上出现过这张 EX」可信；「玩家选中了它」**不可信**。
2. `ex_ledger.获得方式`、`合成前组成卡名` = DEFAULT_FILLED，**禁止**用于策略/构筑/概率。
3. picks 强佐证 15/435（3.4%），UNKNOWN 64.1%——只作弱行为线索。
4. 选卡真值收口改由插桩 Shadow `choice_*.jsonl`；视频线不再深挖。

### 3.4 卡头进度与本批 hitch

- 主包 manifest.events 的 OCR **仅有 kind=treasure n=122**，**无 bond OCR**（蹭车自动化不做羁绊三选）。
- 羁绊结构与 need 主要来自 KB综述 + 视频 + catalog + 09-17 合同（见上）。
- 40 套装名确证（视频激活文本，closeout §一.2）：修仙/异火/三国/体术/海盗/大圣/刀刀/法术/箭术/智力/敏捷/力量/战神/收割者/经济/魔术/魔能/大炮/秘法师/急速/法神/湮灭者/魔法师/元素师/野蛮人/屠戮者/猎魔人/弓神/固守/成长/贪婪/挑战/祝福/体术/肉身成圣/五极山/身法/五行灵根/纷争面纱/点金手 等。

**结论（一句话）**：卡头(x/y)=套装 need 已由视频双信号 9 条+catalog 实证；**海盗真正启动卡是藏宝图(三)（need=3）**；属性门卡 need=4；高级组“能否启动”在 hitch 主证据里几乎全是面板出现而非完成。

---

## ④ 宝物面板、刷新、负面判定（描述红字）

> **本节权威来源**：`G:\刷刷宝\_facts_20260922\treasure_debuff_frames\report.md` + `treasure_catalog.md`（实机GT，13 卡 25 帧，路径与 1600x900 分辨率见 report §1）。不在此重做宝物 OCR 全库。

### 4.1 面板与刷新（实机GT）

| 项 | 数值 | 来源 |
|---|---|---|
| 宝物三选一面板（全库红筛范围） | **688**（主包 134 + C-tmp 554） | treasure_debuff_frames report §4 |
| 去重卡名 | **96**（另剔 2 OCR 杂散名） | treasure_catalog |
| 本批 OpenTreasurePanel | 主包 104；15 包合计 ~550+ | analyze_solo_mechanics |
| 本批实拿（treasure选择） | 主包 44+18 刷新选择；manifest talisman_acquired=48 | 同上 |
| 宝物面板刷新次数来源 | 宝物词条 / 局外效果卡 / 龙珠三星+1、五星+2 | `game_mechanics_kb.json` refresh_ledgers.treasure |
| 龙珠 | 散件进宝物三选；(x/7) 集齐许愿至今未达成 | KB + catalog |

### 4.2 负面语义与红字标定（实机GT，authoritative）

**红字 HSV 规则**：T=40，(H≤10|H≥170)（OpenCV 半量程）& S>120 & V>120；实测色相 H≈162–179（品红偏向）。正样本召回 **10/10**，标定负样本误报 **0/34**。红筛精确率低是设计内取舍（需 OCR+人眼终审）。

**关键负面语义（写入事实表）**：

| 卡名 | 描述原文（帧核验） | 负面核心 |
|---|---|---|
| 贪婪契约 | 立即获得100w金币，3分钟后，本局金币将恒定为 0 | 金币恒定 0 |
| 恶魔契约 | 立即升至25级，在本局游戏中无法再升级 | **无法再升级** |
| 命运骰子 | 50%全属性增幅+25%，50%全属性增幅-15% | 50% 减益 |
| 登神长阶 | 8 分钟内最终全属性 **-35%**；结束后 +30% 全属性等 | 前期大幅减益 |
| 玻璃大炮 | 伤害+25%，**受到的所有伤害提高50%** | 承伤+50% |
| 力/敏/智之极 | **立即扣除当前20%** 的另两维，转为本维 | 双维扣除 |
| 木材梭哈 | 55% 木材翻倍，**45% 木材清 0** | 清零木材 |
| 金币梭哈 | 55% 金币翻倍，**45% 金币清 0** | 清零金币 |
| 经验压制 | 3 分钟杀敌经验 **-70%**；结束后 +3 级 | 经验压制 |
| 提高上限 | 攻击间隔-0.2，攻速-200%（1星：普攻+5%） | 间隔/攻速双负面 |
| 混乱转换 | 基础全属性 90%~120% 随机 | **存疑**（JEV uncertain） |
| 混乱洗牌 | 描述两处不清 | **存疑**，未按负面交付 |

**诅咒之力**（C-tmp 002105 新发现 2 帧，红边框，恢复效果-99%/护甲-10000）：与 handoff 待提交事项对上；**仍不交付**（已入库口径）——事实表注明存在。

### 4.3 96 卡 verdict 总表（供 §⑤ 决策规格直接引用）

| verdict | 数量 | 说明 |
|---|---|---|
| **负面** | **19** | 含上表关键负面 + 等级优势/杀敌梭哈等已知名单 |
| **存疑** | **2** | 混乱转换、混乱洗牌 |
| **正面** | **42** | 神符/资源/技能大师/回天术等 |
| **套装/收集中间态** | **33** | 物理/魔法伤害、提升三件、杀手三件、龙珠等 (x/y) |

src：亲眼核验 21 卡 / 仅 OCR 其余。

### 4.4 现行 choice_policy 命中矩阵（只记录不改仓库）

现行：`config/choice_policy.json:47-73` `negative_patterns` + `negative_names`；判定函数 `src/shuabao/choice_policy.py:1653-1658`。

| 状态 | 卡/语义 | pattern/名单 |
|---|---|---|
| **已命中** | 贪婪契约 | P:将恒定 |
| 已命中 | 提高上限 | P:攻击间隔 / 基础攻击间隔 |
| 已命中 | 杀敌梭哈 | P:杀敌数清0 + N:名单 |
| 已命中 | 金转木 | P:消耗全部金币 + N:名单 |
| 已命中 | 透支力量 | P:宝物效果- + N:名单 |
| 已命中（名单） | 贪婪献祭、伐木契约、等级优势、压制 | N:名单 |
| **缺口** | 恶魔契约「无法再升级」 | 现有「无法升级」**子串不连续，不命中** |
| 缺口 | 命运骰子「增幅-15%」 | 无 pattern |
| 缺口 | 登神长阶「全属性-35%」 | 无 pattern |
| 缺口 | 玻璃大炮「受到的所有伤害提高」 | 无 pattern |
| 缺口 | 力/敏/智之极「扣除」 | 无 pattern |
| 缺口 | 木材/金币梭哈「XX 清 0」 | 仅有「杀敌数清 0」 |
| 缺口 | 经验压制「经验-70%」 | 无 pattern |
| 缺口 | 诅咒之力「恢复效果-/护甲-」 | 无 pattern（且不交付） |

另：`choice_policy.py:1653` 对「压制」有硬编码名；`negative_patterns` 双向拦截「攻击间隔」可能误杀未来降间隔正面卡（dashboard `_pattern_warning`）。

**结论（一句话）**：宝物负面以红字+语义双通道为准（19 负面/2 存疑/42 正面/33 套装）；现行 patterns/names **漏 8 类新负面语义**，⑤ 禁拿名单应按本表而非旧 7 名单。

---

## ⑤ 黑商槽位、刷新、拿取

### 5.1 机制（实机 + KB）

| 项 | 事实 | 证据 |
|---|---|---|
| 货架 | HUD 右下常驻 **5 格**；热键 H | KB综述 G3 帧 |
| 免费刷新 | 每 **180 s** 1 次（倒计时可见“178秒”） | 实机 + user_confirmed |
| 手动刷新 | 扣杀敌（或木材，KB 冲突）；本批 BlackMerchant-refresh 主包 **n=87** | 实机GT |
| 吞噬丹 | 常驻/轮换商品；主包 swallow_pill **n=44**；代码价 400 | 实机GT + CURRENT_CODE |
| 价格形态 | 骷髅图标=杀敌；5 折/8 折标签；50–500 杀敌不等 | 09-17 evidence merchant_prices |
| 等级 | 黑市经验 222/1000 等；杀敌购买也涨经验；升级聊天行“黑市等级升为：2级” | KB + 实机 |
| 自动购买 | **默认零输入**；`auto_gambling_time>0` 才可能放行；Merchant C6 未实机验证 | `game_mechanics_kb.json` batch_status |

### 5.2 本批槽位拿取分布（实机GT）

主包 slot 点击：0:12 / 1:8 / 2:6 / 3:11 / 4:7（n=44 次有槽位 intent）。  
15 包合计 swallow_pill 约 **180**、refresh 约 **360**。  
manifest 主包：`merchant_devour_acquired=44`（与点击一致）。

**结论（一句话）**：黑商=5 槽+180s 免费刷新+杀敌计价；本批大量刷新与吞丹点击（87/44），**但无逐格「标价前后 HUD 杀敌差」对齐，单价与折扣率仍非机制真值**。

---

## ⑥ 复核 09-17 五条结论

| # | 09-17 结论 | 2026-09-22 复核 | 证据落点 | 是否修复 |
|---|---|---|---|---|
| 1 | **卡头/卡名两层**；生产 OCR 只读卡头 | **仍成立**。title_template 仍主导；lexicon 仍混命名空间；视频/帧上两层清晰可见 | `mediator.py:3179` `_fill_bond_slots_by_title_template`；`mediator.py:690` min_score；`choice_lexicon.json` `_comment`/`set_membership`；09-17 合同 §2.6（1796 读 0 卡名） | **未修复**（结构问题在） |
| 2 | **海盗启动卡是藏宝图(三)** | **仍成立**。need=3 三源一致；视频激活/进度交叉印证海盗套装 | `bond_stack_catalog.json` needs.`藏宝图(三)`/`藏宝图`；`dashboard_mechanics.json` bond_buckets.advanced.haidao.gate=藏宝图(三)；video `catalog_import_proposal` 藏宝图 need=3；09-17 `evidence/panel_daodao_cangbaotu.jpg` | 事实确认；**生产包仍未自动优先启动卡** |
| 3 | **隐藏 F 抽卡会保留**（再开同组） | **仍成立**。代码显式统计“同一 F 抽卡重新打开”并有界退避，承认面板指纹持久 | `mediator.py:15756` `[L1] 同一 F 抽卡重新打开`；`mediator.py:4634` 无候选退避；`mediator.py:16174` fingerprint 重开计数；09-17 REAL_LIVE_GT `f_hidden_draw_persists` | **机制未改**（仍为防卡死前提） |
| 4 | **吞噬丹由游戏决定吞哪张** | **仍成立**。脚本只决定“何时用丹”，不选目标 | `mediator.py:5126-5161` UseInventory/WAIT_SWALLOW_PILL_CONFIRM；`mediator.py:5321` fail-closed 随机吞禁止；09-17 REAL_LIVE_GT n=2（均吞中间紫框） | **无需修**（能力在游戏侧） |
| 5 | **木材隐含 +5.5/s**（被动 HUD 之外大额入账） | **仍成立（推断级）**。KB 反推 4.5–5.5/s；handoff 确认木材会降但总量仍升 | KB综述 §1.1 斜率反推；handoff 20260919「5/13 采样下降」；`game_mechanics_kb.json` resources.wood | **未改标**；“只涨不跌”已撤销，速率结论保留 |

**总判**：五条**全部仍成立**；其中 1、5 是结构/速率事实未改，2 是事实已多源钉死但接线未完成，3 是行为前提仍在，4 是游戏侧机制无需修。

---

## ⑦ 缺口清单（缺哪些实机证据、要补采什么）

| 优先级 | 缺口 | 为什么要 | 建议补采 |
|---|---|---|---|
| P0 | **主线 X-Y（尤其 5-5/5-6/6-1）时间戳** | 本批 45 局内段 0 关卡 OCR；时间线只有墙钟 | 局内 HUD 任务栏 ROI 周期 OCR + trace 字段 `main_stage` |
| P0 | **木材/金币/杀敌/G 角标/V 角标 时序采样** | 无法画收入曲线、无法对齐 F/刷新单价 | 每 3 s HUD 快照入 trace；F/刷新点击前后各 1 帧 |
| P0 | **羁绊面板 OCR 进 trace/events**（卡头+卡名） | 主包 bond OCR=0；卡名层仍 0 命中 | 面板槽位双层 OCR；`choice_*.jsonl` Shadow 插桩 |
| P0 | **宝物 patterns 缺口补采语义**（§4.4 8 类） | 恶魔契约等新负面会漏拦 | 不改仓库前提下先出禁拿名单（⑤）；再评估 patterns 只增不删 |
| P1 | **吞噬丹「吞哪张」扩大 n** | 现仅 n=2 | 有意识排布栏位后用丹，录前后帧 |
| P1 | **黑商逐商品价签 + 购买前后杀敌差** | 400/折扣率仍是代码/零散帧 | 单商品独占购买事件 |
| P1 | **海盗链 P1→P5 全程**（集齐藏宝图→开进码头→悬赏令→战舰） | 启动后每步无实机 GT | 专局只推海盗；黄金猿仍 fail-closed |
| P1 | **V 刷新次数（刷新 N）来源与扣减** | 与 F 花费易混 | 刷新前后角标 OCR |
| P2 | **卡组 members / route_order 文字版** | handoff 已列 11 条链路缺 members | Owner 文字；只进 `guide` 桶 |
| P2 | **视频 picks 真值替代** | picks 64.1% UNKNOWN | 插桩 Shadow `choice_*.jsonl`（已收口） |
| P2 | **经验压制 2 星尾行被卡框遮挡** | 描述不完整 | 换分辨率/滚动条帧 |
| P2 | **混乱转换/混乱洗牌存疑裁决** | 不能进默认禁拿以外的策略 | 更多同卡帧 + Owner |
| P2 | **单人纯 solo_ingame_chain 合格包** | 现主证据是 hitch 进局内；solo_ingame_chain_* 被禁用（未进局内） | 新采集必须确认 MAIN_LINE≥完整 Boss 段 |
| P1 | **技能抢占 vs Owner 时序裁决** | `mediator.py:4570` 与 skill_bond_timing 相反 | TASK_H 基线 + Owner 裁（见 §8.1/8.5） |
| P1 | **体术 note / 贪婪 note 在 official_strategy 未改** | 仍写旧攻略语义 | 只改文档层需 Owner；本表已标已推翻（§8.6） |

---

## ⑧ 攻略 / KB 单人决策规则（证据分级专节）

> 用途：给 ⑤ 决策规格做差异对照的事实源。每条标 **证据等级 + n**。  
> 等级：实机GT / 视频OCR / KB配置 / Owner口述 / 攻略(S*/D*) / 竞品 / 推断 / **已推翻**。  
> 结构保证：`docs/policy/POLICY_V01_IMPLEMENTATION_CONTRACT_20260908.md` —— **GUIDE_TIER 恒 OUT_OF_SCOPE 进策略层**；攻略数字不得进策略层（证据附录 `POLICY_V01_EVIDENCE_APPENDIX_20260908.md`）。

### 8.1 优先级顺序（取卡 / 调度）

| 序 | 规则 | 证据 | n / 出处 |
|---|---|---|---|
| 0 | 强制弹窗独占；fail-closed 零输入 | KB配置+代码 | `official_strategy_defaults` / 仓库硬规矩 |
| 1 | **差 1 张吞噬/合成**压过全部顺序（秒选） | 实机GT+代码 | LOST_LOGIC §2；`choice_policy.py` 已持有合成优先 |
| 2 | **先拿羁绊**；羁绊近成型或木材不溢出后才拿其他 | **Owner口述** 20260920 | `TASK_G_SKILL_BOND_MECHANICS_20260920.md`；KB `resources.skill_bond_timing`（`game_mechanics_kb.json`） |
| 3 | round1_must：**祝福→成长→经济→贪婪→挑战**（第一轮前做完） | 攻略（抖音无胆超人5月/在家零四一7月，user 20260813 转述）+ 实机 live | `official_strategy_defaults.json` `bond_priority.round1_must` / `round1_note` |
| 4 | **属性整链（门卡→中环→次环→UR）排在生存卡之前** | 实机复盘 + KB配置 | 同文件 `round2_attr_chain`；「有湮灭者却先拿体术」被 Owner 点名 |
| 5 | must_take 羁绊：**急速**（出了基本必选） | 实机/口述 | `bond_priority.must_take` |
| 6 | round3 生存：提速→体术→固守→陷阵 | 攻略+live（提速仅 guide） | `bond_trees`；提速 status=**guide**（lab 零出现） |
| 7 | round4 可选：生命/血势/血魔/暴击/致命/大炮（长局木富再做） | 攻略 | `bond_priority.round4_optional` |
| 8 | 高级卡组/秘境顺序：**海盗优先**（经济核心）；神兽在三国前；龙族军团靠后（EX 后仍污染池） | 攻略 USER_SCREENSHOT | 09-17 合同 §9 `guide_screenshots/secret_realm_bond_take_order.png`；S12 秘境攻略 |

**与现行代码冲突（待裁，不改码）**：

| 冲突 | Owner/机制 | 现行代码 | 落点 |
|---|---|---|---|
| 技能积压抢占 | 技能点**零机会成本**，不该紧急抢 | `_solo_plan_panel`：**技能积压≥8 无论木材先点技能** | `src/shuabao/mediator.py:4570-4578`；9 局中 6 局该规则影响 ≥40% 决策（handoff 20260919） |
| 贪婪收益口径 | 三散件合计 150木+888杀敌+6000金 | 旧 KB/攻略曾写成「套装效果」 | **已推翻**（KB综述 §2.2；卡面套装=随机吞4张） |
| 体术效果 | 卡面=**斗气场域** 80%力量自适应伤 | 旧攻略/`official_strategy_defaults` 仍写「破甲 10%」 | **已推翻**（KB综述 §2.2；`bond_trees.体术.note` 仍旧文，标冲突） |
| 黑商购买范围 | Owner 08-27：吞噬丹+木材+2/5折 | 09-08 起**只买吞噬丹**（全模式） | LOST_LOGIC §4 `d7d6dc2`【疑似误伤 P1】 |
| F4 | KB：打不过才按 | 09-03 起非乘客**每 20s 自动按** | LOST_LOGIC §4 `8262ad8`【疑似误伤 P1】 |

### 8.2 门卡 / 启动卡规则

| 规则 | 证据 | n |
|---|---|---|
| 属性门卡 `gate_card`（智力/力量/敏捷），**gate_need=4** → 解锁专属链 → UR | KB配置+lab 实机 | `official_strategy_defaults.attr_routes`；lab 152022/152437（chain_status=**confirmed**） |
| 链结构同构：**门4 → 中环4 → 次环3 → UR3**，最少 14 抽 ≈ **1400 木/链** | 攻略+KB（成本为攻略） | `_cost` 注释；**攻略，以游戏内为准** |
| 支线 support（魔法师/元素师/箭术/战术/血誓…）**不是必经**，正式局可后置 | KB配置 | attr_routes.support / support_note |
| 高级组启动卡：藏宝图(三)/姜子牙/乱世三国/亡灵天灾/焚诀/幽灵系带… | 实机卡面+catalog | §3.3；need 真源 `bond_stack_catalog.json` |
| 「差 1 张」时无视白名单顺序秒选 | 实机GT+代码 | choice_policy 已持有合成优先 |
| 剑术不进白名单（普攻剑气流专属） | 攻略 | `bond_trees.剑术` status=guide lab_skip |
| 蓄力射击 never_pick | 攻略 S3 | `official_strategy_defaults` never_pick / notes（S3 负收益 -50% CD） |

### 8.3 资源阈值

| 阈值 | 含义 | 证据 | n |
|---|---|---|---|
| F 价 **100**（1 min 后封顶） | 木材<100 → F 不可能推进 | 实机GT | KB综述 F 提示框 |
| 羁绊刷新 **40** | OCR `刷新 40` | 实机GT | 多局面板 |
| 木材缓冲 **500**（Owner） | <500 先技能/其他 | Owner口述 | KB综述 J2 |
| 属性链预算 **1400 木/条** | 两条 2800、三条 4200 | **攻略** | official_strategy `_cost`；以游戏内为准 |
| 高级 EX 预算 2300–3200 木 | 攻略估 | 攻略 | 09-17 §2.4 |
| 吞噬丹 **400 杀敌** | 代码价，未实机对齐 | KB配置/CURRENT_CODE | `mediator.py:4291` |
| 黑商免费刷新 **180 s** | user_confirmed+实机 | 实机GT | KB resources.kill_count |
| 暴击率 **>50%** 暴击套才是正收益 | 攻略 | 攻略 | bond_priority.round4_note |
| 面板 episode 上限（用户存档曾=5） | 空开也计数会误伤 | 实机GT+代码 | LOST_LOGIC P0；`mediator.py:14701` 一带 |

### 8.4 刷新 / 放弃条件

| 规则 | 证据 | n |
|---|---|---|
| 白名单 **hard** 模式：未命中不拿 | KB配置 | `choice_policy` / `global_safe_defaults.bond_whitelist_mode=hard` |
| soft→hard、祝福不再系统必拿（需勾选） | 语义变化 Owner 已拍板 | LOST_LOGIC §2 `3434f0a` |
| OCR miss **禁止**烧木刷新（羁绊） | 代码收紧 | `b5d924d`；choice_policy OCR miss 不刷 |
| 技能 focus miss 可在已验证刷新钮上刷 | 代码 | `skill_refresh_on_focus_miss` |
| 视频拒卡 205 次模式：耗木刷新 + 弃与主属性不匹配散卡 | 视频OCR n=205 | `video_policy/refusals.csv` |
| 无安全候选：仅模板验证刷新钮 + 预算未尽才刷 | KB配置 | `choice_policy.json` `_refresh_on_no_safe_note` |
| 负面宝物默认不选；allow_negative 逐卡打勾才放行 | KB配置 | `choice_policy` negative_* / allow_negative |
| must_take 宝物跨品质优先（历史）→ 现仅最高品质档内 | **语义变化待 Owner 确认** | LOST_LOGIC `d4aa92c`；与 09-17 must_take 并存写冲突 |
| 宝物先滤负面再按品质 | 代码 | choice_policy 宝物段 |

### 8.5 时序：技能零成本 vs 羁绊截止期（Owner 20260920）

| 项 | 机制 | 证据 |
|---|---|---|
| 技能点 | **无上限、不过期、早学晚学等效**；积压≠风险 | Owner口述；KB `skill_bond_timing.skill_points` |
| 羁绊 | **有成长与合成周期**；晚拿可能赶不上；部分卡有条件吞噬 | Owner口述；示例「击杀200」「时间60秒」**非穷尽** |
| Owner 策略 | 先羁绊；成型或木材不溢出后再其他 | Owner口述 |
| 现行冲突 | 技能积压≥8 紧急抢占（与上相反） | `mediator.py:4570`；待 TASK_H 基线+Owner 裁 |

### 8.6 已推翻 / 冲突表（不得静默取舍）

| 旧说法 | 现状 | 依据 |
|---|---|---|
| 体术=破甲 10% | **已推翻** → 卡面「斗气场域」80%力量自适应伤 | KB综述 §2.2 卡面原文 |
| 贪婪套装给 150木+888杀敌+6000金 | **已推翻** → 是三散件合计；套装效果=随机吞4张 | KB综述 §2.2 |
| 木材只涨不跌 | **已推翻** | handoff 20260919；20260918_210044 5/13 下降 |
| 属性链「整跑通拿到 UR」 | **已推翻** → lab 只推进到 UR 环 (1/3) | official_strategy chain_evidence 20260824 审计 |
| 生命 need=4 | 与视频/Owner **need=3** 冲突 | catalog conflict 行；Owner 20260919 |
| 修仙启动=纳气诀 vs 小绿瓶/练气期 | **CONFLICTED**（KB stages 无 status） | 09-17 §2.5；KB综述 |
| 黑商常驻4格扣木材 vs 扣杀敌 | **CONFLICTED** | 09-17 §2.1 |
| EX 出现=玩家选中 | **禁止**（视频收口） | video_policy README 边界 |

### 8.7 攻略影像（7 张，`C:\Users\10639\Desktop\攻略参考\`）

| 文件 | 读出情况 |
|---|---|
| img_v3_0215k_4f20f47b…png | 攻略截图（技能流/羁绊顺序类）；本表以已入库 S*/D* 文字与 video_policy 为准，**图未逐字重 OCR** |
| 其余 6 张 img_v3_* | 同上；看不清者标「攻略图未读出」 |

来源编号见 `docs/REBORN_WOW_GAME_STRATEGY_RESEARCH.md`（S1–S17 / D1–D12；S3 奥术箭高可信、S12 秘境/赌木、S8 梭哈流）。  
`docs/research/SCRIPTABLE_LOGIC_MAP_20260812.md` 提供攻略→脚本 P0/P1/P2 映射（未在本表逐条展开，⑤ 差异时对照）。

---

## 附录 A · 宝物 policy 引用总表（⑤ 可直接引用）

汇总自 §4.3–4.4：

| 分类 | n | policy 现状 | ⑤建议 |
|---|---|---|---|
| 负面 | 19 | 7 名单 + 部分 pattern；**8 类语义缺口** | **默认禁拿全 19**；存疑 2 默认禁拿 |
| 存疑 | 2 | 无命中 | 默认禁拿，待裁 |
| 正面 | 42 | 无强制 | 按流派/资源策略 |
| 套装 | 33 | 无特殊 | 按 (x/y) 凑套 |
| must_take | 6 名（ONEPIECE 等） | `must_take_names` | 保持 |
| 诅咒之力 | 1（已入库不交付） | 待提交 | 维持不交付 |

## 附录 B · 脚本与输出

| 脚本 | 作用 |
|---|---|
| `scripts/peek_trace_schema.py` | trace 字段/相位/决策分布 |
| `scripts/analyze_solo_mechanics.py` | 局内段时长、黑商/宝物动作、事件 OCR 分类 |
| `scripts/extract_ocr_panels.py` | ocr_shadow/panels/关卡 token |
| `out/aggregate.json` | 45 段时长 + 黑商/宝物汇总 |
| `out/summary_*.json` | 每包摘要 |
| `out/ocrpanels_*.json` | OCR/面板/manifest 侧车 |

复跑：

```powershell
python G:\刷刷宝\_facts_20260922\mechanics_solo\scripts\analyze_solo_mechanics.py
python G:\刷刷宝\_facts_20260922\mechanics_solo\scripts\extract_ocr_panels.py
```

## 附录 C · 外部交付交叉引用

| 路径 | 用途 |
|---|---|
| `G:\刷刷宝\_facts_20260922\treasure_debuff_frames\` | 宝物负面 25 帧 + report + catalog（§4 权威） |
| `G:\刷刷宝\_facts_20260919\video_policy\` | 视频 need 提案、EX 出现、拒卡 205（§2–3） |
| `docs/reviews/evidence_20260916/solo_orchestration/KB_MECHANICS_SYNTHESIS.md` | 单人机制主综述（不重证） |
| `git show docs/mechanics-contract-20260917:docs/reviews/mechanics_contract_20260917/MECHANICS_CONTRACT_RESEARCH_20260917.md` | 09-17 五条结论出处 |
| `docs/CURRENT_STATUS_AND_HANDOFF_20260919_MECHANICS.md` | 词库/JEV/时序机制边界 |
