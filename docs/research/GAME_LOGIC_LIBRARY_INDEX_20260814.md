# 游戏逻辑库总索引（2026-08-14）

> **给后续写脚本 / 图鉴 / 自学习的 agent：先查本页，再打开对应 JSON。**<br>
> 本页是索引，不是第七份表。数值与规则以权威文件字段为准；本页只回答「去哪查、接没接」。<br>
> 机器可读底库：[`config/game_mechanics_kb.json`](../../config/game_mechanics_kb.json)（整份仍 `wired_to_decision=false`）。<br>
> 人类可读底库：[`OFFICIAL_GAME_MECHANICS_KB_20260814.md`](OFFICIAL_GAME_MECHANICS_KB_20260814.md)。

**采信优先级（已定，缺口不许用攻略数字填）：**<br>
游戏内官方说明（`status=official_help`）> 实机 OCR / 夹具 > 用户截图 > 用户口述（`source=user_confirmed`）> 外部攻略。

**本轮范围：** 交付物 A（索引 + F1/F2 入库）。交付物 B（L1 算法接线）未开工——须等 Infra 确认 L1 车道空闲（其 D3/D4 同车道）。

---

## 0. 十分钟速查

| 问题 | 答案 | 出处 |
|---|---|---|
| 刷新花什么资源？ | **先问哪种刷新。** 羁绊刷新=木头；黑商刷新=杀敌（每 180s 免费 1 次）；宝物/技能/英雄卡刷新=宝物词条或局外效果卡给的次数，不花杀敌/木头。开 F/G 是抽卡，不是刷新。 | `refresh_ledgers` |
| 衍生卡什么时候进池？ | **全部**前置技能到手之后。缺一张 = 池子里没有，刷新也刷不出来。 | `game_mechanics_kb.card_pool_rules.prereq_all`；卡面前置串在 `skill_card_catalog.cards[].prereq` |
| 哪几条是脚本禁止项？ | **聊天绝对禁止：`-zs` 以及圣剑切形态 `-永恒/-岚/-终焉/-1/-2/-3`。禁止自动点装备栏（黄金猿）。** F4、压力转移分情况。 | `script_forbidden`；`script_situational` |
| F / G 各花什么？ | F=木头抽羁绊；G=技能点抽技能。技能点来自升级（每级 1 点）。 | `hotkeys.F` / `hotkeys.G`；`resources.skill_points` |
| F1 / F2 是什么？ | **F1=操作切回自身英雄**；**F2=回基地**。用户 2026-08-14 口述，`source=user_confirmed`。F1 作「面板无响应恢复焦点」仅登记为候选，**未接线**。 | `hotkeys.F1` / `hotkeys.F2` |
| 脚本现在接了哪几条？ | 真接上的只有 **G 优先于 F**。白/绿先刷、目录压 OCR、审判排斥曾误登记，源码未调用。 | `game_mechanics_kb.partially_wired` |
| 技能卡几种颜色？ | **橙 > 紫 > 蓝 > 白。没有红、没有粉。** 绿边是宝物。长测「红巨型剑气」是橙边被 HSV 采成 red。 | `card_pool_rules.skill_card_colors` |
| 各套最终形态？ | 海盗无 EX=UR 毁灭战舰；其余 EX。法天象地卡面标签神通；攻略当大圣终点。禁止自动键入圣剑切形态 `-永恒/-岚/-终焉`。 | `ex_capstones` + lexicon |
| 刀刀 / 异火 / 大圣怎么查？ | 刀刀 need=3，三件套→萌新→大成→EX解放的圣剑；图纸链见 `daodao_chain.guide`（未上帧）。大圣实机只有(0/3)天命人；攻略终点法天象地，卡面标签神通。异火黄阶只开 N。 | lexicon + `daodao_chain` / `dasheng_chain` / `yihuo_fenjue_pool` |
| 封神 / 亡灵 / 神兽 EX？ | 圣人/兵主/祖龙卡面已入库。攻略蓝图在 `fengshen_chain` / `wangling_chain` / `shenshou_chain`。异兽蛋 60s 开池已有 OCR。亡灵天灾 need=3。不写攻略张数。 | lexicon + 三条 `*_chain` |
| 军团 / 龙族 / 三国 / 修仙 EX？ | 萨格拉斯/世界末日/吞食天地/大乘期卡面已入库。蓝图在 `juntuan_chain` / `longzu_chain` / `sanguo_chain` / `xiuxian_chain`。修仙集齐出练气期已 OCR。技能卡无 EX。 | lexicon + 四条 `*_chain` |
| 技能卡有 EX 吗？ | **没有。** 技能最高橙。EX 只在羁绊最终形态。衍生技能卡是全部前置到手后才能在 G 三选刷出，不是合成。 | `prereq_all` + `skill_card_colors.no_ex_tier` |
| 海盗 / 宝藏怎么查？ | 无 EX=UR 毁灭战舰。藏宝图(三) need=3。黄金猿是装备栏左键开宝藏，禁止自动点。 | `haidao_chain` + lexicon |

---

## 1. 概念 → 权威文件 → 字段 → 是否接线

接线列含义：

- **已接** = 已进 `choice_policy` / mediator 决策，并登记在 `partially_wired`
- **部分接** = 读了配置但语义不完整（例如前置只排序不否决；稀有度已读但目录大片空洞）
- **未接** = 知识在库，决策不读
- **禁止** = fail-closed，永远不接（现仅 `-zs`）
- **分情况** = 允许条件已定，未接线
- **候选另立项** = 可登记，本板块不接线

### 1.1 资源账本

| 概念 | 权威文件 | 字段 | 接线 |
|---|---|---|---|
| 杀敌数 = **黑商刷新**（每 180s 免费 1 次） | `game_mechanics_kb.json` | `resources.kill_count`；`refresh_ledgers.kinds.black_merchant` | **未接**。官方 7 页写成「刷新英雄/宝物/技能」；user 2026-08-14 纠正。原文留 `official_text` |
| 木头 = F 抽羁绊 **和** 羁绊三选刷新 | 同上 | `resources.wood`；`refresh_ledgers.kinds.bond` | **部分接**：F 面板已走；刷新扣木未门控。B2 阈值因此更站得住。单价未知 |
| 宝物 / 技能 / 英雄卡刷新次数 | 同上 | `resources.refresh_charges`；`refresh_ledgers.kinds.{treasure,skill,hero_card}` | **未接**。只来自宝物词条或局外效果卡（一入局能看见次数）。没有次数不要刷。所谓「白/绿先刷」并不在 choose_action 里 |
| 技能点 = 升级每级 1 点，G 抽技能 | 同上 | `resources.skill_points`；`hotkeys.G`；`panels.skill_gacha` | **已接** `skill_points_via_G_before_wood_F`：有技能焦点时技能结束留 G，羁绊结束回 G |
| 经验 → 升级 | 同上 | `resources.exp` | 未接公式（不需要） |
| 金币 = 专属升级（每 10 级选词条） | 同上 | `resources.gold`；`panels.exclusive_upgrade` | **未接**。旧研究「金币主用途=黑市」已纠正。黑市是否另耗金币：未知 |
| 掉宝率 | 同上 | `resources.drop_rate`；`special_attributes.drop_rate` | 未接 |

抽卡 ≠ 刷新。四种刷新账本（`refresh_ledgers`，`source=user_confirmed`，未接线）：

| 刷新 | 扣什么 | 不要当成 |
|---|---|---|
| 羁绊三选刷新 | 木头 | 技能/宝物刷新 |
| 技能三选刷新 | 宝物词条或局外效果卡的**次数** | 杀敌、木头、技能点 |
| 宝物三选刷新 | 同上 | 杀敌、木头 |
| 英雄卡刷新 | 同上 | 黑商（不是一回事） |
| 黑商刷新 | 杀敌；每 **180 秒**免费 1 次 | 「黑商刷英雄卡」（假类别，已删）；购买序（仍在 `do_not_auto_enable`） |

局外效果卡：一进局就能看到还剩几次，多半是充值 / 抽奖 / 前置装备。缺口不填攻略数字。官方 `basic_attr` 原文与本表冲突，以本表写脚本，待实机核对。

### 1.2 技能卡池规则

| 概念 | 权威文件 | 字段 | 接线 |
|---|---|---|---|
| 衍生卡进池 = 全部前置 | `game_mechanics_kb.json` | `card_pool_rules.prereq_all` | 官方规则已入库。脚本**不拿前置否决实机候选**（20260814：次级箭/爆炸箭矢被误判非法连丢技能点） |
| 焚诀阶位决定异火卡池 | `game_mechanics_kb.json` | `card_pool_rules.yihuo_fenjue_pool` | **未接**。黄阶=N 已实机；4 张 N 词条以 OCR 为准。拆解表 06–13 在 `breakdown_scan_unverified` |
| 刀刀三件套→萌新→大成→圣剑 | `game_mechanics_kb.json` | `card_pool_rules.daodao_chain` | **未接**。need=3 已实机。一/二阶段图纸 `guide`，除三元重戟外无帧 |
| 大圣天命人→法天象地 | `game_mechanics_kb.json` | `card_pool_rules.dasheng_chain` | **未接**。实机只有(0/3)天命人。攻略残躯/套装/大成未上帧。EX 卡面神通 |
| 封神姜子牙→圣人 | `game_mechanics_kb.json` | `card_pool_rules.fengshen_chain` | **未接**。姜子牙 t=765 无 tooltip。攻略 6/9/法宝跳未上帧，不写 need |
| 亡灵天灾→兵主 | `game_mechanics_kb.json` | `card_pool_rules.wangling_chain` | **未接**。实机 need=3。攻略 100残骸/符文10 不写 need。英雄卡巫妖≠克尔苏加德 |
| 神兽异兽蛋→祖龙 | `game_mechanics_kb.json` | `card_pool_rules.shenshou_chain` | **未接**。60s 自吞开池已 OCR。同名互吞/64绿未上帧 |
| 军团燃烧的远征→萨格拉斯 | `game_mechanics_kb.json` | `card_pool_rules.juntuan_chain` | **未接**。EX 不拆军团池。27/3虚空未上帧 |
| 龙族巨龙军团→世界末日 | `game_mechanics_kb.json` | `card_pool_rules.longzu_chain` | **未接**。开池已 OCR。祈求10未上帧。迦拉客隆=迦拉克隆 |
| 三国乱世三国→吞食天地 | `game_mechanics_kb.json` | `card_pool_rules.sanguo_chain` | **未接**。每400杀吞已上帧。每营8张未上帧 |
| 修仙三件套→大乘期 | `game_mechanics_kb.json` | `card_pool_rules.xiuxian_chain` | **未接**。need=3；神秘戒指+练气期已 OCR。小绿瓶仍宝物 |
| 技能卡无 EX | `game_mechanics_kb.json` | `card_pool_rules.skill_card_colors.no_ex_tier` + `prereq_all` | **未接估值**。衍生卡前置齐了才能刷，不是合成 |
| 海盗藏宝图→战舰；黄金猿开宝藏 | `game_mechanics_kb.json` | `card_pool_rules.haidao_chain` | **未接**。need=3 已实机。禁止自动点装备栏 |
| 恐鳌戒指 | `game_mechanics_kb.json` | `card_pool_rules.kongao_ring` | **未接**。精选帧 21–23。need 未测 |
| 各套最终形态 EX/UR | `game_mechanics_kb.json` | `card_pool_rules.ex_capstones` | **未接**。全部无法吞噬。聊天切形态禁止自动键入 |
| 卡面前置串 / 互斥串 | `skill_card_catalog.json` | `cards[].prereq` / `cards[].exclude`（220 张 / 16 系） | **部分接**：前置只排序（`skill_chain_rank`），不否决 |
| 单向排斥 | `game_mechanics_kb.json` + catalog | KB `card_pool_rules.asymmetric_exclude`；catalog `审判之雷.exclude=磁暴` + `exclude_asymmetric=true` | **已接** `judgment_thunder_excludes_magnetic_storm` |
| never_pick | `skill_card_catalog.json` | `cards[].never_pick`（现仅 **蓄力射击**） | **已接**（目录否决） |
| 已吞噬不能再进化 | `game_mechanics_kb.json` | `card_pool_rules.devoured_no_evolve` | **未接**估值；吞噬决策须在吞前做完 |
| 羁绊集齐自动吞噬 | 同上 | `card_pool_rules.bond_auto_devour` | 游戏侧自动；脚本认「差 1 张吞噬」优先 |
| 吞噬分几种 | 同上 | `card_pool_rules.devour_kinds` | **未接**。集齐自动 ≠ 击杀随机吞 ≠ EX 掷骰吞。异火底栏计数不是 need |
| 三张全不在卡组仍放弃 | 用户 20260814 已定 | — | **已接**。不要「优化」成拿卡组外主技能 |

**异火 / 刀刀对机制库的帮助（已入库、未接决策）：**

| 新事实 | 咬合哪条旧规则 | 脚本现在该怎么想 |
|---|---|---|
| 焚诀阶位开门控异火池（黄阶=只 N，已实机） | 和技能「全部前置才进池」同类，但是**羁绊卡池** | 黄阶局刷出 N 不是 bug。想刷帝炎要先让焚诀进化；玄/地/天未上帧，不许当实机 |
| 每 200 杀随机吞 1 异火；底栏 `异火(168)` | 不是 `bond_stack_catalog.need` | **禁止**写成 need=168。白名单对的是散件名（阴阳双炎…），不是角标「异火」 |
| 刀刀 F 见 `刀刀(0/3) 幽灵系带` | 硬白名单只认字面「刀刀」会狂刷（17:45 事故） | 认套装件：幽灵系带/护腕/空灵挂坠；`set_membership=刀刀` 已修词典。差 1 张仍优先 |
| 三件套→萌新开刀刀池→大成→EX 圣剑 | 和三线 UR 链同构，但不在 `bond_trees` 四轮里 | 实验室勾散件。攻略补 3/7 一阶段图纸、5/6 二阶段。点金手第三张再刷是攻略，未接 |
| 切形态 `-永恒/-岚/-终焉` | 攻略写成 `/蓝` `/中烟` | **蓝=岚、中烟=终焉、斜杠不采。禁止自动键入** |
| 法天象地卡面神通 | 攻略当大圣 EX | 实验室 `exclude_ex` 已挂大圣。残躯链未跑通。EX 卡面没有回血/闪避/截断 |
| 大成：CD-20%、触发+50%、多段伤害、吞其余刀刀出 UR 图纸 | CDR 硬顶 80%；主技能触发≠衍生；剑气/龙卷风每段都算 | 估值未接。多段流（剑气/龙卷风/闪电链）吃刀刀，不是奥术箭专属 |
| 帝炎 EX：燃烧伤害+300%、异火燃烧 10s 每秒 300% 自适应 | 官方燃烧=每秒 100% 火系物理 | 未证实是否同一状态。叠法未知，不猜 |
| 圣剑 EX：拆刀刀池+掷骰吞；聊天切永恒/岚/终焉 | 与 `-zs` 同属聊天 | **禁止自动键入**（已进 `script_forbidden`）。岚的急速+100 vs 硬顶 80% 未测 |
| 圣剑「无视闪避」 | 官方闪避覆盖真伤 | 可能是这条攻击跳过闪避，不是推翻全局。未测 |
| 法天象地卡面 = 神通 EX | 攻略当大圣终点 | 残躯链未上帧。回血/闪避是大成件不是 EX 卡面 |
| 异兽蛋 60s 后自吞开神兽池 | OCR 已钉；攻略吞食丹跳过未上帧 | 不要把 64 绿写成 need |
| 亡灵天灾 need=3 | 攻略当单张启动 | 保持 3。英雄卡巫妖进词典但不属亡灵，防认成巫妖王 |
| 兵主冰霜符文技能伤害×1.25 | 卡面已钉；攻略 100残骸/符文10 未上帧 | 不写 need |
| 圣人技能急速+30 / 技能伤害+30% | 卡面已钉；攻略 24张/2400木未上帧 | 不写 need |
| 异火攻略 3/6/9/12/22 | 实机只钉住黄→玄=3 | 不写 need=22。焚决=焚诀 |
| 萨格拉斯不拆军团池 | 卡面无 remove_pool；灭世斩破甲2% | 攻略 27/3虚空不写 need |
| 世界末日不拆龙族池 | 卡面浩劫*1.3 | 祈求10/五色未上帧。迦拉客隆=迦拉克隆 |
| 吞食天地每400杀随机吞 | 卡面已钉 | 每营8张/只能吞蓝 未上帧 |
| 修仙集齐出练气期 | t=198 OCR | 小绿瓶仍宝物。渡劫50%未上帧 |
| 技能卡无 EX | 最高橙；EX 是羁绊 | 衍生卡前置齐了才刷 |
| 海盗无 EX=UR 战舰 | 卡面开池 N+重拳先生 | 悬赏令出战舰 vs 吞12 两说 |
| 黄金猿装备栏左键 | user_confirmed | 禁止自动点。黄金元是错字 |
| 贪婪 need=3 | lab 2/3 | 攻略写2张，不改 |

攻略里的「异火地震流」是技能（地震+爆炎箭）+ 异火羁绊起手，和「异火套装」不是同一张表。不要把攻略层数填进 KB。

### 1.3 稀有度

| 概念 | 权威文件 | 字段 | 接线 |
|---|---|---|---|
| **技能卡四色**（user 2026-08-14） | `game_mechanics_kb.json` | `card_pool_rules.skill_card_colors` | **未接**。游戏内：橙>紫>蓝>白。无红、无粉。绿边是宝物 |
| 截图边框稀有度底库 | `skill_card_rarity.json` | `cards[].rarity`（只许白/蓝/紫/橙） | **未接**。文档曾写 `catalog_rarity_over_ocr` / `_with_catalog_rarity`，源码没有这个函数。实机稀有度来自 HSV 边框 |
| 覆盖现状（2026-08-14 盘点） | 同上 vs catalog | catalog 220 张；rarity **41** 张 | **严重不足**。有边框的几乎只有冰霜新星 / 闪电链 / 爆炎箭。**整系 0 条**：奥数箭、奥数激光、奥数射线、剑气、寒冰箭、天雷、普攻、地震、龙卷风、电磁网、陨石、飓风、火球。主技能存档图标不是升级卡边框 |
| 推断稀有度（白=单前置等） | `SKILL_CARD_CATALOG_20260813.md` | 文档表，**不是**运行时字段 | **禁止当权威**。有冲突以截图边框为准 |
| 名字 conf 与边框稀有度 | 长测 trace intel L231 | — | **未解耦**。所谓「红巨型剑气」是橙边被 HSV 采成 `red`，再因 conf 0.575&lt;0.60 被跳过转拿紫卡。B1 最高优先 |

B1 催截图（给素材 agent，不填攻略推断色）：剑气系 14、陨石 12、地震 13、普攻系 22、奥术树（奥数箭 20 + 奥数激光 11 + 奥数射线 9）。入库走既有幂等脚本，不手编稀有度。B1 接线时技能品质序改成橙>紫>蓝>白；技能面板 HSV `red` 当 orange 或丢弃；宝物仍留 green。

### 1.3b 拿卡逻辑（对照源码，2026-08-14）

三面板共用 `choose_action`。OCR live 时 mediator 把槽位交给它；名字 conf **&lt; 0.60 的槽直接当没看见**。三张全不在卡组仍放弃（user 已定）。

**局内循环（已接）**：G 技能 → F 羁绊 → V 宝物 → 进化 → 装备 → 拾取 → 黑商 → 神器，再回到 G。

**技能 G**

1. 只认控制室勾选的预设（`Settings.skills`）。
2. 预设里同时出现多张：按 `quality_order` 稀有度优先（脚本现仍是红>橙>紫>蓝>白>绿；游戏技能最高档是橙）。
3. 同稀有度：用户勾选顺序，再靠左槽。
4. 预设一张都没有 → 刷新（最多 3 次，这是脚本上限不是游戏上限）→ 放弃。
5. **不会**拿预设外的卡，即使那张是橙卡。
6. 目录 `never_pick`（蓄力射击）、前置否决、审判之雷排斥磁暴、白卡先刷新：函数在 `skill_catalog.py`，**mediator 没调用**。前置只允许排序、禁止否决（次级箭事故）。

**羁绊 F**

1. 硬白名单：没勾选一律不选。要勾**散件规范名**（幽灵系带），不能只勾「刀刀」「异火」。
2. 命中白名单：用户勾选顺序优先，同名再比稀有度。
3. 三槽都不在白名单 → 等 → 刷新 → 放弃/隐藏。品质色和「第一张」旁路已切断。
4. 套装差 1 张优先：策略函数有，mediator 传进去的 `set_progress` 恒为 `None`，所以这条**没跑起来**。

**宝物 V**

1. 负面名字/描述先剔除（贪婪献祭等）；UI 勾了才放行。
2. `must_take_names`（ONEPIECE 等）写在 JSON，mediator 的 `treasure_presets` 恒为空，**没拿必拿名单**。
3. 无预设时按品质降级；OCR 读不到名字时才允许宝物走边框色。绿边是合法最低档。

**不要当成已接的**

- 白/绿技能先刷新
- 目录稀有度压过 OCR
- 木头 &lt;100 不开 F
- 焚诀/刀刀/EX 卡池门控

### 1.4 存档等级效果

| 概念 | 权威文件 | 字段 | 接线 |
|---|---|---|---|
| 16 系存档门槛 | `skill_archive_unlocks.json` | `skills[].unlocks[]`（`kind`=`unlock_card` / `stat` / `waive_prereq` / `grant_on_learn` / `other`） | **部分接**：仅调用方显式传入 `archive_levels` 且 `level_status=verified` 时放宽前置 / 提高齐射优先级。默认空 = 旧拿卡 |
| 缺档 | 同上 | `gaps` | 5 系 16 档全齐（奥术箭 / 爆炎箭 / 奥术激光 / 奥术射线 / 闪电链）。其余见 JSON `gaps` |
| 加数据纪律 | `tools/merge_skill_archive_screenshots.py` | — | **只走该脚本**，禁止手改 JSON。卡名对不上 catalog → `tests/test_skill_knowledge_consistency.py` 拦住 |

### 1.5 羁绊链路、张数、四轮优先级

| 概念 | 权威文件 | 字段 | 接线 |
|---|---|---|---|
| 同名合成张数 `need` | `bond_stack_catalog.json` | `needs.<规范名>.need`（66 条，含刀刀=3）；`capacity=10` | **已接**（词典闭环，白名单全闭合） |
| 解锁树（谁开谁） | `official_strategy_defaults.json` | `bond_trees`（`prereq` / `unlocks` / `tier` / `status`） | 实验室消费；**桌面「应用流派」未接** |
| 四轮取卡顺序 | 同上 | `bond_priority`：`round1_must` → 属性链（含 UR）→ `round3_survival` → `must_take` → `round4_optional`；`lab_skip` 丢掉第四轮 | 实验室白名单按此拼；「差 1 张吞噬」压过全部顺序 |
| 三线 UR 链 | 同上 | `attr_routes.{intelligence,strength,agility}.chain` | 实验室已消费。结构：门卡 4 → 中环 4 → 次环 3 → UR 3 |
| 5 套流派 build | 同上 | `builds[]`（`arcane_open` 默认） | 实验室已消费；桌面未接 |
| 硬白名单 | `choice_policy.json` | `bond.whitelist_mode=hard` | **已接**。未勾选一律不选。套装要勾**散件规范名**（幽灵系带），不能只勾角标「刀刀」「异火」 |

张数与攻略分歧（已按实机/截图，**不要改回攻略数**）：大炮 2≠3；魔术 2≠3；经济 3≠2~3；体术 3≠4。刀刀 need=3 已测。异火**不写** need。

刀刀 / 异火**不在** `bond_trees` 四轮里。实验室白名单靠 lexicon `set_membership` + probe `cards`。

### 1.6 乘区与硬顶

| 概念 | 权威文件 | 字段 | 接线 |
|---|---|---|---|
| 攻速硬顶 1000% | `game_mechanics_kb.json` | `attributes.attack_speed.cap_pct`；`caps.attack_speed_pct` | **未接**（B5 可选，先写清再接） |
| 技能急速 CDR 硬顶 80% | 同上 | `special_attributes.skill_haste.cap_pct`；`caps.skill_haste_pct` | **未接** |
| 多重/弹射伤害系数 30%–100% | 同上 | `attributes.multi_damage` / `bounce_damage`；`caps.multi_damage_pct` / `bounce_damage_pct` | **未接** |
| 多重/弹射不触发普攻特效 | 同上 | `damage_rules.multi_bounce_no_aa_proc`；`attributes.multi_count.triggers_aa_effects=false` | **未接** |
| 「所有伤害」「伤害增幅」独立乘区 | 同上 | `special_attributes.all_damage` / `damage_amp`；`damage_rules.independent_zones` | **未接**估值 |
| 「视为普攻伤害」不吃技能伤害 | 同上 | `special_attributes.aa_damage` / `skill_damage`；`damage_rules.aa_vs_skill` | **未接**估值 |
| 主技能触发 ≠ 衍生 | 同上 | `damage_rules.main_skill_trigger`（次级箭/小冰箭/磁暴不算；剑气/龙卷风每段都算） | **未接**估值 |
| 护甲减物理**和**魔法 | 同上 | `attributes.armor` | 未接（认知纠正） |
| 闪避覆盖真伤 | 同上 | `special_attributes.evasion.covers` | 未接。圣剑「无视闪避」未证实是否例外 |

### 1.7 状态效果

权威：`game_mechanics_kb.status_effects`（两页合并，圣盾以 `status_p2` 为准）。人类表见官方 KB §4.4。

| id | 名 | 要点字段 | 接线 |
|---|---|---|---|
| `stun` / `freeze` / `paralyze` | 眩晕 / 冻结 / 麻痹 | `kind=control` | 未接 |
| `burn` | 燃烧 | `dps_coeff_pct=100`，火系物理 | 未接。帝炎「异火燃烧 / 燃烧伤害+300%」是否同条未测 |
| `frostburn` | 燃霜 | 200%，最多 3 层 | 未接 |
| `iceflame` | 冰焰 | 200% 自适应，最多 5 层 | 未接 |
| `frostbite` | 冻伤 | 50% 冰系魔法，最多 5 层 | 未接 |
| `shock` | 感电 | `bonus_all_attr_pct=25`，不跳字 | 未接 |
| `slow` / `weakness` | 减速 / 衰弱 | 移速 -30% / -80% | 未接 |
| `heavy_wound` / `disintegrate` / `vulnerable` | 重创 / 瓦解 / 易伤 | 受伤 +20 / +25 / +20 | 未接；是否互叠：未知 |
| `armor_break` | 破甲 | 护甲 -10% | 未接 |
| `holy_shield` | 圣盾 | 每层抵 1 次伤害 | 未接 |

### 1.8 热键与面板

| 键 | 动作 | 权威字段 | 来源 | 接线 |
|---|---|---|---|---|
| F | 羁绊抽卡（耗木头） | `hotkeys.F` | `official_help` | 已走 F 面板；木头门控未接 |
| G | 技能抽卡（耗技能点） | `hotkeys.G` | `official_help` | 已接技能优先 |
| C | 主线挑战 | `hotkeys.C` | `official_help` | 已有 L1 挑战路径 |
| **F1** | **操作切回自身英雄**（防 G/V/F 面板无法操作） | `hotkeys.F1` | **`user_confirmed`**（2026-08-14） | **候选另立项**：可作「面板无响应恢复焦点」，本板块不接 |
| **F2** | **回基地**（视角偏离或要点秘境/传家宝点不到） | `hotkeys.F2` | **`user_confirmed`**（2026-08-14） | **未接**。蹭车骨架有 F1/F2 占位，旧口述「两次 F2」作废，以本条为准 |
| F4 | 清场上挑战怪 | `hotkeys.F4`；`script_situational[clear_challenge_f4]` | `user_confirmed` | **分情况**：打不过就按；打得过禁止误按。未接 |
| 专属升级 | 耗金币，每 10 级词条 | `panels.exclusive_upgrade` | `official_help` | 热键未知，未接 |
| V | 脚本现认宝物面板 | 交接 13:40 / mediator 循环 | 非本 7 页 | 循环已走；不是官方帮助原文 |

现网代码里另有「F1 选卡兜底 shadow」——那是脚本自己的影子键，**不是**游戏「切回自身英雄」。禁止复用。

### 1.9 禁止项与分情况（user 2026-08-14 解禁 F4 / 压力转移）

| 操作 | 权威字段 | 官方后果 | 脚本（2026-08-14 拍板） |
|---|---|---|---|
| 输入 `-zs` / `-ZS` | `script_forbidden[suicide_chat]` | 自杀，并清空全部复活次数 | **仍绝对禁止键入**。攻略「开局令不佳 ZS 重开」不得自动化 |
| 输入 `-永恒` / `-岚` / `-终焉` / `-1` `-2` `-3` | `script_forbidden[sword_form_chat]` | 解放的圣剑切形态 | **禁止自动键入**（与 -zs 同类）。默认永恒。未接线也不许键入 |
| 按 F4 | `script_situational[clear_challenge_f4]`；`hotkeys.F4` | 清掉自己场上挑战怪（含压力转移送来的） | **打不过就按**（主线/资源/压过来的怪都算）。还打得过时禁止误按。未接；「打不过」判定未钉 |
| 点压力转移 | `script_situational[pressure_transfer]`；`multiplayer.pressure_transfer` | 改刷怪、资源归属、胜负绑 1P | **跟车/蹭车一进游戏就点**。自己开房 / 独狼 / 当 1P 禁止误点。未接；`lobby_hitch.live_enabled` 仍 false |

`official_strategy_defaults.do_not_auto_enable`：**黑市自动购买序**、**木头梭哈/ZS 重开**、**杀敌投资 58 秒窗口**、**云端选卡**。不做。

### 1.10 胜负与多人（只读）

| 概念 | 字段 | 接线 |
|---|---|---|
| 胜：时限内打掉最终 BOSS | `win_lose.win` | 未接公式 |
| 负：阵亡或超时 | `win_lose.lose` | 未接 |
| 免费复活 1 次 | `win_lose.free_revive` | 未接 |
| 携手同心（每层掉宝 +5%，最多 3） | `multiplayer.together_buff` | 未接；跟车点压力转移后 1P 会叠这层 |

---

## 2. 单一数据源纪律

任何新知识先问「归哪个文件」。**禁止开第七份机制表。**<br>
机制库就是下面 6 份 JSON；`choice_lexicon` / `choice_policy` 是运行词典与决策开关，不是第 7 份机制表。`skill_meta.json` 只是桌面预设短码，不是机制权威。

| 要改的东西 | 只写这里 | 不要写到 |
|---|---|---|
| 改名 / OCR 别名 / 同音近形 / 套系归属 | `config/choice_lexicon.json`（`entries.<规范名>.aliases` / `confusions` / `set_membership`） | catalog 里可以挂 `aliases` 作卡面异体，但归一化以 lexicon 为准 |
| 羁绊同名合成张数 | `config/bond_stack_catalog.json`（`needs`） | 不要把 `need` 再抄进 `bond_trees` 当第二权威；`bond_trees.need` 是展示副本，冲突以 catalog 为准 |
| 升级卡效果 / 前置串 / 互斥串 / never_pick | `config/skill_card_catalog.json` | 不要在研究 md 里另造一张卡表；推断稀有度不准回写成 catalog 字段 |
| 必拿 / 负面宝物 / 品质序 / 白名单模式 | `config/choice_policy.json`（`treasure.must_take_names` / `negative_*`；`bond.whitelist_mode`；`quality_order`） | 不要在 KB 里写决策开关 |
| 存档等级档位 / 取消前置 / 齐射不再降伤 | `config/skill_archive_unlocks.json` | **只走** `tools/merge_skill_archive_screenshots.py`，禁止手改 |
| 官方机制（资源账本、**分面板刷新**、乘区、状态、卡池规则、禁止项、热键） | `config/game_mechanics_kb.json`（刷新只写 `refresh_ledgers`） | 攻略数字不许填缺口；人类可读同步 `OFFICIAL_GAME_MECHANICS_KB_20260814.md`。禁止再写「刷新=杀敌」一句话 |
| 截图边框稀有度 | `config/skill_card_rarity.json` | 禁止用 catalog 文档的推断色填；无边框就留空 |
| 流派 build / 四轮优先级 / UR 链 / 解锁树 | `config/official_strategy_defaults.json` | 改完若要进桌面默认，再同步 `default_settings.json` / `skill_meta.json`（另开任务） |

冲突裁决：官方帮助页 > 实机 OCR/夹具 > 用户截图 > 用户口述 > 外部攻略。同音近形（血誓/血势/血魔；提速/急速）**绝不互设别名**。

---

## 3. 仍未知（从 KB §8 迁入，本页维护）

机器副本：`game_mechanics_kb.unknown[]`。有实机/官方证据才能划掉，**不许用攻略数字填**。

| 未知项 | 为什么不能猜 | 谁可能补 |
|---|---|---|
| F 抽羁绊单次木头消耗 | 开面板，不是刷新；官方无单价 | 实机木头差值 |
| 羁绊三选刷新单次木头 | 已定花木头，未定多少 | 实机木头差值 |
| G 抽技能是否即三选一面板 | 官方只写「G 消耗技能点」；脚本现认三选一 | 实机对照 |
| 黑商刷新单次杀敌数 | ~~每 180s 免费 1 次已定；单价未知~~ 已实测：刷新按钮 60（yihuo_ t=208） | ✅ 2026-08-15 板块8（见 §4） |
| 哪些词条 / 局外卡给宝物·技能·英雄卡刷新次数 | 只知性状，不知清单 | 卡面截图 + 入局帧 |
| 局外效果卡剩余次数怎么读 | 一入局能看见，锚点未钉 | 入局夹具 |
| 专属升级每级金币、词条池、热键 | `panels.exclusive_upgrade.unknown` | 官方/截图 |
| 力/敏/智百分比伤害递减公式 | 官方只写「递减」 | 官方 |
| 致命一击基础倍率；命中/闪避公式 | 官方只写触发与覆盖面 | 官方 |
| 重创 / 瓦解 / 易伤是否互叠；状态持续时间 | 官方只写各自百分比 | 官方/实机 |
| 黑市消耗是否另计 | 7 页官方说明未提黑市 | 官方/实机（在 `do_not_auto_enable` 之前不要接购买序） |
| 除审判之雷 ↔ 磁暴外还有哪些不对称排斥 | 官方只给这一对 | 卡面「排斥」原文 + 实机进池观察 |
| F1 恢复焦点的成功条件（哪些面板/镜头状态有效） | 用途已 `user_confirmed`，未实机钉 | 夹具前后帧 |
| F2 回基地后可点范围 | 用途已 `user_confirmed`，未实机钉 | 秘境/传家宝前后帧 |
| 「打不过」按 F4 的实机判定 | 已定要按，未定看什么信号（血量 / 挑战失败提示 / 超时）。**不猜阈值** | 真机夹具 |
| 焚诀玄/地/天阶开哪些池 | 黄阶=N 已实机；更高阶仅用户图鉴 | 实机悬停焚诀高阶 |
| 拆解表 06–13 八张异火是否本局真刷出 | 无 OCR/精选帧；用户图鉴标玄/地阶 | 单独 crop + OCR |
| 恐鳌戒指 need | 精选帧有散件，无 (x/y) | F 角标或已吞噬 |
| 刀刀一/二阶段图纸 | 除三元重戟图纸 t=765 外无帧；萌新200杀发图纸未证实 | 悬停已吞噬 + 实机三选 |
| 齐天大圣是否等于法天象地 | 卡面神通；攻略当大圣 EX。残躯链未上帧，不当相等 | 跑通残躯/套装/大成 |
| 技能卡无红色 | 已 `user_confirmed` 橙紫蓝白；HSV 仍采 red | B1：技能序去掉 red；橙边勿标红 |
| 圣剑掷骰数量；岚急速+100 vs CDR 80% | 卡面有，结算未测 | 实机 |
| 圣剑无视闪避 vs 闪避覆盖真伤 | 可能只是这条攻击跳过闪避 | 实机 |
| 帝炎异火燃烧 vs 官方燃烧 | 是否同状态、+300% 怎么叠 | 实机 DoT |
| 封神榜 6/9、法宝三连跳各 5 | 姜子牙仅文件名；无 tooltip | 悬停封神榜/天仙 |
| 亡灵残骸 100 / 符文各≥10 / 邪爆 2 次 | 兵主卡面有符文词条，没有计数 | 实机 F 角标 |
| 神兽同名互吞与 4 UR→祖龙 | 异兽蛋 60s 已钉；进化链无帧 | 栏内两张相同神兽 |
| 异火 6/9/12/22 | 只钉住黄阶吞 3→玄 | 悬停高阶焚诀 |
| 军团 27 吞 + 3 扭曲虚空 | 萨格拉斯卡面有破甲，没有计数 | 第三张扭曲虚空瞬间 |
| 龙族祈求 10 / 五色龙王 | 巨龙军团开池已钉 | 悬停龙巢/祈求 |
| 三国每营 8 张 | 乱世三国见名；吞 400 已钉 | 阵营 UR 成型帧 |
| 修仙渡劫 50% / 五极山 | 练气期已 OCR；小绿瓶仍宝物 | 渡劫成功/失败帧 |
| 海盗 6/9/12 与橙悬赏出战舰 | 战舰开池已钉卡面 | 悬停制造混乱/罗杰斯 |
| 黄金猿装备栏左键锚点 | 用途已 user_confirmed | 装备栏前后帧。禁止自动点 |
| 宝藏每 3 张 / 安卡 | 无帧 | F9 图鉴 |

---

## 4. 本轮新知识入库（2026-08-14）

| 键 | 动作 | source | 脚本 |
|---|---|---|---|
| **F1** | 操作切回自身英雄。用途：G/V/F 面板无法操作时把操作焦点拉回自己。 | `user_confirmed` | 可登记为「面板无响应时按 F1 恢复操作焦点」**候选恢复手段**。**接线另立项，本板块不做。** |
| **F2** | 回基地。用途：视角偏离，或需要点秘境 / 传家宝却点不到。 | `user_confirmed` | 未接。蹭车旧口述「两次 F2」作废。 |
| **F4** | 打不过场上挑战怪时按，清场。 | `user_confirmed` | **已解禁、未接线。** 打得过禁止误按。 |
| **压力转移** | 跟车 / 蹭车一进游戏就点。 | `user_confirmed` | **已解禁、未接线。** 自己开房 / 1P / 独狼仍禁止误点。 |
| **刷新分账本** | 羁绊刷木头；黑商刷杀敌（180s 免费 1 次）；宝物/技能/英雄卡刷次数（词条或局外卡）。 | `user_confirmed` | **已入库 `refresh_ledgers`，未接线。** 官方「杀敌刷英雄/宝物/技能」原文保留备查。 |
| **异火 / 刀刀 / EX / 恐鳌** | 焚诀门控异火池（4 张 N 的 OCR 词条已校正）；刀刀三件套链；11 套最终形态；恐鳌戒指两件。吞噬分几种。 | `live_174547` + 用户卡面 | **已入库 `yihuo_fenjue_pool` / `daodao_chain` / `kongao_ring` / `ex_capstones` / `devour_kinds` / `live_174547_sidecars`。未接决策。** 拆解表 06–13 不得升格。 |
| **技能卡四色** | 橙>紫>蓝>白。无红、无粉。绿=宝物。 | `user_confirmed` | **已入库 `skill_card_colors`。未改 `quality_order` / HSV。** 长测「红卡」按橙边+低 conf 理解。 |
| **刀刀/大圣攻略链** | 图纸与残躯/大成补进 KB+lexicon。实机优先。 | 抖音无胆超人+在家零四一、KK | **`daodao_chain.guide` / `dasheng_chain`。未接决策。** 未把图纸加入实验室白名单。 |
| **封神/亡灵/神兽/异火 EX 攻略链** | 蓝图入库。实机优先：异兽蛋 60s、亡灵天灾 need=3。不写攻略张数。 | 同上 | **`fengshen_chain` / `wangling_chain` / `shenshou_chain` / `yihuo_fenjue_pool.guide`。未接决策。** |
| **军团/龙族/三国/修仙 EX 攻略链** | 蓝图入库。修仙练气期、巨龙军团开池已 OCR。技能卡无 EX。 | 同上 | **`juntuan_chain` / `longzu_chain` / `sanguo_chain` / `xiuxian_chain`。未接决策。** |
| **海盗/宝藏** | 战舰卡面+藏宝图 need=3。黄金猿装备栏左键。 | 抖音+user_confirmed | **`haidao_chain`。未接。禁止自动点装备栏。** |
| **龙珠散件** | 宝物三选面板出龙珠：三星=宝物免费刷新+1；五星球=+2；二星=力量增幅类[1星]+3%；四星=英雄卡*1（另见+4技能点）；七星=金币+10000、木材+10000（013304 段读 +100，两读并存待核）。套装角标(x/7)=已收集数（0/7→1/7→2/7 自洽）。集齐7颗召唤神龙许愿未达成。一/六星球无证据。 | 板块8 实机抽帧（daodao_/yihuo_/013304_） | **已入库 `refresh_ledgers.kinds.treasure.dragon_ball_notes`。未接线。** 证据 `fixtures/treasure_merchant_dragonballs_20260815/` |
| **黑市机制实测** | 黑市每180秒免费刷新1次；商店等级越高物品越好；每秒自动+1经验，杀敌购买也+经验，经验满升级（经验条 369/500 互证；升级聊天行 t=875/1596）。折扣标签对应商品原价：2折→60 与 2折→400 并存（非固定价）、5折→150、8折→320、原价 300/500。刷新按钮 60。 | 板块8 实机抽帧（yihuo_ t=208 / 013304_ t=1463.5） | **已入库 `refresh_ledgers.kinds.black_merchant`（discount_tiers 校正）。未接线。** `do_not_auto_enable` 仍禁止自动购买 |

已写入 `game_mechanics_kb.json`。`wired_to_decision` 保持 `false`。`-zs` 与圣剑切形态仍禁止自动键入。

---

## 5. 已接 / 挂账对照（给 B 阶段，先别动代码）

`partially_wired` 对照源码后只留 1 条：`skill_points_via_G_before_wood_F`（L1 循环先 G 后 F）。

曾误登记、**choose_action 未调用**：`skill_refresh_skips_white_green`、`catalog_rarity_over_ocr`。审判之雷排斥只在 `skill_catalog.is_skill_choice_legal`，mediator 没走。

B 阶段按序、**一条一个 commit**（须 Infra 确认 L1 空闲）：

| 序 | 内容 | 层 | 备注 |
|---|---|---|---|
| B1 | 稀有度目录补洞 + conf / 稀有度解耦 + 技能无红 | L1 | **最优先**。边框不得被名字 conf 连坐。技能序橙>紫>蓝>白；HSV red 当橙。缺口不填攻略色 |
| B2 | 木头 &lt;100 不开 F；&lt;40 不在羁绊面板刷新 | L1 | 阈值放 `choice_policy.json`，默认开。治刷新空转 |
| B3 | `draw_insufficient` 不再烧刷新 | L1 | 夹具 `fixtures/longtest_20260814/focus/e_t00336.0_draw_insufficient.jpg` |
| B4 | trace 增加 `policy.reason` | L1 | 板块 4 自学习输入 |
| B5 | CDR/攻速硬顶、多重不触发特效进估值 | L1 | 可选，用户点头后；先在本库写清推导 |

---

## 6. 相关人类文档（只读，冲突以本页 + JSON 为准）

| 文件 | 角色 |
|---|---|
| [`OFFICIAL_GAME_MECHANICS_KB_20260814.md`](OFFICIAL_GAME_MECHANICS_KB_20260814.md) | 7 页官方说明的人类版 |
| [`TREASURE_MERCHANT_DRAGONBALLS_20260815.md`](TREASURE_MERCHANT_DRAGONBALLS_20260815.md) | 板块8：龙珠/宝物/黑商实机拆解（3 录像 + 根目录粗扫），夹具 `fixtures/treasure_merchant_dragonballs_20260815/` |
| [`SKILL_CARD_CATALOG_20260813.md`](SKILL_CARD_CATALOG_20260813.md) | 220 张效果/前置；推断稀有度勿当权威 |
| [`SKILL_BOND_MECHANICS_AND_SYNERGY_20260814.md`](SKILL_BOND_MECHANICS_AND_SYNERGY_20260814.md) | 存档等级解锁研究摘录 |
| [`BOND_SKILL_AND_ROUTES_20260813.md`](BOND_SKILL_AND_ROUTES_20260813.md) | 基础羁绊树、三线卡组 |
| [`SCRIPTABLE_LOGIC_MAP_20260812.md`](SCRIPTABLE_LOGIC_MAP_20260812.md) | 旧 DONE/CFG/NEED；资源账本已被官方 KB 纠正 |
| [`docs/handoff_20260814/03_AGENT_GAME_LOGIC_KB.md`](../handoff_20260814/03_AGENT_GAME_LOGIC_KB.md) | 本板块执行提示词 |

旧研究把「刷羁绊」和「刷新」混写、把金币主用途写成黑市、把 `DEFAULT_MAX_REFRESHES=3` 当成游戏规则——以本页 §1.1 为准。
