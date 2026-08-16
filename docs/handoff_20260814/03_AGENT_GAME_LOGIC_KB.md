# 板块 3 · 底层逻辑库梳理 + 算法升级 — 执行 Agent 提示词

> 直接把本文整份复制给执行 agent。层归属：**感知/策略纯函数 + 配置**（L1 拿卡算法部分单独提交）。
> 先读仓库根 `AGENTS.md`（硬规矩）与 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md` 顶部三条。

## 你的任务（一句话）

把散在 6 份 JSON + 5 份研究文档里的游戏底层逻辑收成**一份带索引的权威逻辑库**，然后按优先级把其中「已核实、能提升拿卡质量」的几条接进 `choice_policy`——每条接线独立提交、独立开关、独立测试。

## 现有资产（不要重造，只梳理 + 接线）

| 文件 | 内容 | 状态 |
|---|---|---|
| `config/game_mechanics_kb.json` | 官方 7 页说明：资源账本、乘区、状态、卡池规则、技能四色 | `wired_to_decision=false`。源码真接上的只有 G 优先于 F。白绿先刷 / 目录压 OCR / 审判排斥曾误登记 |
| `config/skill_card_catalog.json` | 220 张升级卡 / 16 系：效果、前置、互斥、never_pick | 已接（前置只排序不否决） |
| `config/skill_archive_unlocks.json` | 16 系存档等级解锁（5 系 16 档全齐） | 已接（仅显式传入 archive_levels 时生效） |
| `config/skill_card_rarity.json` | 截图边框稀有度底库（只许白/蓝/紫/橙） | **覆盖严重不足**。目录压 OCR 未接到 choose_action。技能卡没有红/粉 |
| `config/bond_stack_catalog.json` | 羁绊合成张数 + 证据（含刀刀=3） | 词典闭环，白名单全闭合。异火**不要**写 need（底栏计数≠张数） |
| `config/official_strategy_defaults.json` | 5 套流派 build、三线 UR 链、四轮羁绊优先级、bond_trees 解锁树 | 实验室已消费；桌面「应用流派」未接 |
| `docs/research/OFFICIAL_GAME_MECHANICS_KB_20260814.md` 等 | 人类可读版 + 采信优先级 | 权威 |

采信优先级（已定，写进逻辑库首页）：**游戏内官方说明 > 实机 OCR/夹具 > 用户截图 > 用户口述 > 外部攻略**。缺口不许用攻略数字填。

## 交付物

### A. 逻辑库总索引（纯文档，先做）

新建 `docs/research/GAME_LOGIC_LIBRARY_INDEX_20260814.md`：

1. 一张「概念 → 权威文件 → 字段 → 是否接线」矩阵，覆盖：资源账本、技能卡池规则（进池前置/单向排斥/never_pick）、稀有度、存档等级效果、羁绊链路与张数、四轮优先级、乘区与硬顶（CDR 80% / 攻速 1000% / 多重弹射 30–100%）、状态效果表、禁止项（-zs 绝对禁止；F4 / 压力转移分情况，见 user 2026-08-14 解禁）。
2. 「单一数据源纪律」表：改名/别名→`choice_lexicon`；张数→`bond_stack_catalog`；升级效果→`skill_card_catalog`；必拿/负面→`choice_policy`；等级档位→`skill_archive_unlocks`（只走 `tools/merge_skill_archive_screenshots.py`，不手改）；官方机制→`game_mechanics_kb`。任何新知识先问「归哪个文件」，禁止开第七份表。
   - **异火（2026-08-14，OCR 词条已校正）**：黄阶只开 N 池 + 吞噬 200/3 进化 → `yihuo_fenjue_pool`。已上帧 4 张 N 的数值以 `evidence_ocr.json` 为准（风怒=火/风，幽冥=燃烧/暴击，玄黄=敏/护甲/火）。拆解表 06–13 八张在 `breakdown_scan_unverified`，不得升格。`异火(168)` 不是 need。
   - **刀刀（2026-08-15 攻略补链）**：实机三件套→萌新→UR大成→EX圣剑。一/二阶段图纸在 `daodao_chain.guide`。`/蓝`=`岚`，`/中烟`=`终焉`。三元重疾→三元重戟。不要把图纸加入实验室白名单。
   - **大圣（2026-08-15 攻略补链）**：实机只有(0/3)天命人。攻略终点法天象地，卡面标签神通。残躯/套装/大成不写 need。EX 卡面没有回血/闪避。
   - **封神/亡灵/神兽/异火 EX（2026-08-15 攻略补链）**：`fengshen_chain` / `wangling_chain` / `shenshou_chain` / `yihuo_fenjue_pool.guide`。实机优先：异兽蛋 60s 开池已有 OCR；亡灵天灾 need=3；不写 6/9/100/10/64/22。英雄卡巫妖≠克尔苏加德≠巫妖王。焚决→焚诀。不要把攻略卡加入实验室白名单。
   - **军团/龙族/三国/修仙 EX（2026-08-15 攻略补链）**：`juntuan_chain` / `longzu_chain` / `sanguo_chain` / `xiuxian_chain`。萨格拉斯/龙族 EX 不拆本池已与卡面一致。修仙集齐出练气期已 OCR。技能卡无 EX；衍生卡是前置齐了才刷，不是合成。不写 27/8/10/50%。小绿瓶仍宝物。迦拉客隆→迦拉克隆。
   - **海盗/宝藏（2026-08-15 攻略补链）**：`haidao_chain`。无 EX=UR 毁灭战舰。黄金猿是装备栏左键，禁止自动点。黄金元→黄金猿。贪婪 need=3。不要把攻略卡加入实验室白名单。
   - **最终形态（2026-08-14 用户卡面）**：`card_pool_rules.ex_capstones` + lexicon。海盗无 EX=UR毁灭战舰；其余 EX。全部无法吞噬。**禁止**自动键入 `-永恒/-岚/-终焉/-1/-2/-3`。**禁止**自动点装备栏开黄金猿。
3. 「仍未知」清单（从 KB §8 迁入并维护）：F/G 单次消耗、刷新杀敌数单价、专属升级词条池、递减公式、其余不对称排斥对等。
4. **新知识入库**（user 2026-08-14 口述，标 `source=user_confirmed`）：热键 **F1=操作切回自身英雄**（防 G/V/F 面板无法操作）、**F2=回基地**（视角偏离或需要点秘境/传家宝点不到时）。写入 `game_mechanics_kb.json` 热键节。「面板无响应时按 F1 恢复操作焦点」可登记为候选恢复手段，但**接线另立项**，不在本板块做。

### B. 算法升级（每条一个 commit，L1 层）

按序做，做一条验一条：

1. **稀有度目录补洞 + conf/稀有度解耦 + 技能无红**（最高优先）：
   - user 2026-08-14：技能卡只有橙紫蓝白，没有红。长测「红巨型剑气」是橙边被 HSV 采成 red，再因 OCR conf 0.575<0.60 被跳过、转拿紫卡（trace intel L231）。稀有度判定与名字置信度是两个问题，**边框颜色判定不应被名字 conf 门槛连坐**。
   - 向用户/素材 agent 开列缺失卡清单（剑气系、陨石、地震、普攻系、奥术树），催截图入库；入库走既有幂等脚本模式。
   - 接线：技能品质序改成橙>紫>蓝>白；技能面板 HSV `red` 当 orange 或丢弃；宝物仍留 green。回归用原样帧钉住：橙卡在 conf 低时仍按稀有度优先。
2. **木头阈值**（交接文档挂账已久）：木材 <100 不开 F 羁绊面板；<40 不在羁绊面板刷新。这是治「刷新→无变化→隐藏→重开」空转的正解。阈值放 `choice_policy.json` 可调，默认开。
3. **抽卡不足（draw_insufficient）不再烧刷新**：长测夹具 `fixtures/longtest_20260814/focus/e_t00336.0_draw_insufficient.jpg` 已固化，识别到「不足」文案时 WAIT/关闭而不是刷新。
4. **trace 增加 `policy.reason` 字段**：每次 SELECT/REFRESH/GIVEUP 落盘决策理由（稀有度/预设/前置链/吞噬/白绿刷新），这是后面所有算法迭代的观测基础，也是板块 4 自学习的输入。
5. （可选，用户点头后）CDR/攻速硬顶、多重不触发特效接入宝物/技能估值——先在逻辑库里写清楚推导，不急着接。

## 硬边界

- 每条接线**独立提交**，不与选关 L0、外壳、找房混。提交前 `python tools/release_gate.py` 退出码 0。
- `game_mechanics_kb.json` 顶层 `wired_to_decision` 保持 false，只在 `partially_wired` 里逐条登记。
- **`-zs` 仍禁止**做成任何自动化。F4 / 压力转移已解禁、分情况：跟车进局点压力转移；打不过按 F4。自己开房/1P/打得过时仍禁止误触。接线另立项，不和拿卡 B 混提交。
- C2 契约：新增局内状态字段必须同步 `INGAME_POLLUTION` 清单（`tests/contract/test_l0_lobby_chain_contract.py`）。
- 三张全不在卡组时仍点放弃（user 20260814 已定，不要"优化"掉）。
- 黑商自动购买序、木头梭哈、云端选卡在 `do_not_auto_enable` 名单里，不做。

## 验收

- 逻辑库索引文档能让一个新 agent 在 10 分钟内回答「刷新花什么资源」「衍生卡什么时候进池」「哪几条是脚本禁止项」并指出出处文件。
- B1/B2/B3 各有用真机 trace/夹具钉住的回归测试；`pytest tests -q` 与冻结回放不倒退。
- 回写 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`：接了哪几条、哪些链路需要重新真机验证。
