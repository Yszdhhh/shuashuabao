# 板块 2 · 图鉴功能（游戏逻辑库 + 技能效果库 + 羁绊效果库的展现层）— 执行 Agent 提示词

> **第 1 步已落地（2026-08-14 15:25）：** `src/gamescript/atlas_view.py` + `tests/test_atlas_view.py`。无 atlas.json。第 2 步 UI 未开工。

> 直接把本文整份复制给执行 agent。层归属：**外壳**。
> 权威规格已存在：`docs/research/CONTROL_CENTER_PET_ATLAS_PLAN_20260814.md` §7（图鉴）+ §13（P2 测试），本文只做增量约束与开工顺序。先读它，再读 `AGENTS.md`。

## 你的任务（一句话）

把羁绊、技能、技能等级效果、技能卡、宝物、黑商做成脚本内的**只读图鉴**（类似游戏图鉴/百科），数据全部来自现有 JSON 的运行时 join（AtlasView），并留一条受控的「应用到本局」单向出口。

## 铁律（方案已拍板，不要重新发明）

1. **禁止再写一份卡名表**（没有 atlas.json）。图鉴代码只 join 这些权威源：
   - 规范名/别名 ← `config/choice_lexicon.json`（条数以 JSON 现数为准，不要写死）
   - 升级卡效果/前置/互斥 ← `config/skill_card_catalog.json`（220 张/16 系）
   - 主技能标签/预设 ← `config/skill_meta.json` + `config/skill_labels.json`
   - 等级解锁效果 ← `config/skill_archive_unlocks.json`（图鉴按档位展示「Lv36：爆炸箭矢取消前置」等）
   - 稀有度 ← `config/skill_card_rarity.json`
   - 羁绊张数/证据 ← `config/bond_stack_catalog.json` + `config/fetter_labels.json`（36 短码）
   - 羁绊链路/解锁树 ← `official_strategy_defaults.json` 的 `attr_routes` + `bond_trees`（只读引用，不复制）
   - 套装件 ← lexicon `set_membership` ∈ `_JOIN_BOND_SETS`（异火/刀刀/封神/神兽/龙族/三国/军团/亡灵/修仙/神通/海盗/法宝…）；最终形态 ← `ex_capstones`。**不要**再抄进 atlas.json
   - 负面/必拿宝物 ← `config/choice_policy.json`
   - 图标 ← `assets/Images/skills/*.png`、`assets/Images/cards/*.png`、`fixtures/treasure_must_take/`、`fixtures/ur_attr_routes/`、`fixtures/ex_finals_20260814/`（最终形态卡面；174547 JPG 未进仓时路径保持空）
2. **默认只读**。运行中禁止任何「应用到白名单」；空闲时应用需二次确认，且只能改 16 系（≤4）/ 羁绊短码（≤6）/ 负面宝物放行，升级卡名永远进不了 `settings.skills`。
3. 来源标签三档：**实机 / 攻略 / 待补**（字段已有：`seen`、`source`、`status`、空 `description`；词典 `version_seen=live-*`→实机，`catalog-*`→攻略）。空说明显示「待补」，**不得编数值**。
4. 黑商页第一版是**空态 + 待补清单**（无 lexicon merchant 条目、无全屏帧），不得编货品表。
5. 羁绊两列都展示：有短码（可进白名单）/ 仅知识不可勾。不要为补全去猜短码。异火 / 刀刀目前**无 fetter 短码**，全部 knowledge_only。
6. **异火证据分层（2026-08-14）：** 黄阶 + 阴阳双炎/风怒龙炎/幽冥毒火/玄黄炎 = 实机（`evidence_ocr.json`）。词条以 OCR 为准：风怒=火/风+4%（不是物/魔）；幽冥=燃烧+10%+暴击；玄黄=敏+100/护甲+3/火+5%。拆解表 06–13 八张仍是攻略，不得标实机。恐鳌戒指/生命之球/守护指环已 join（need 未测）。`异火(168)` 不是 need。
7. **最终形态已入库（2026-08-14 用户卡面）：** `fixtures/ex_finals_20260814/`。海盗无 EX（UR 毁灭战舰），其余 EX。全部无法吞噬。法天象地标签是**神通**，不要标成大圣完成。解放的圣剑聊天切形态，图鉴只展示，禁止「应用到本局」去键入 `-永恒` 等。

## 开工顺序

### 第 1 步：AtlasView 数据层（不依赖板块 1，可立即开工）

- `src/gamescript/shell/atlas_view.py`（若 shell 包尚未由板块 1 建出，先放 `src/gamescript/atlas_view.py`，板块 1 落地后搬家）：纯函数 join + 可缓存，输出统一条目结构 `{规范名, 类别, 系/张数, 效果, 前置/互斥, 稀有度, 等级档位, 证据标签, 图标路径}`。
- **异火 / 刀刀 / 恐鳌 join 已落地：** `_JOIN_BOND_SETS` 含异火/刀刀/恐鳌戒指等。效果走 `_note`。套装链路 join KB `daodao_chain` / `yihuo_fenjue_pool` / `kongao_ring`。不要把拆解报告 06–13 标成实机。
- 一致性测试（方案 §13 P2 要求）：投影里的技能规范名 ⊆ lexicon ∪ catalog；负面宝物名 = policy；羁绊链引用的名字都能在词典解析。这是防三份表漂移的机器闸。

### 第 2 步：图鉴 UI（依赖板块 1 的 shell P0 完成）

- 次级页（不占首页主路径）：筛选（技能系/升级卡/羁绊/宝物/黑商）+ 搜索（规范名+别名）+ 卡片网格 + 详情。
- 羁绊详情画出链路（门卡 4 → 中环 4 → 次环 3 → UR 3）与解锁树（prereq/unlocks），UR 三件套用 `fixtures/ur_attr_routes/` 实机图。
- 技能详情按存档等级档位列解锁表；若用户已填/已采集 `skill_archive_levels`，高亮当前档位（与板块 4 P0 产出打通，读不到就不高亮）。
- 「应用到本局」按钮：空闲可用 → 确认框列 diff → 写入设置；运行中 `setEnabled(False)`。

### 第 3 步：证据缺口回报

图鉴天然暴露缺口（无图标、无说明、无稀有度）。把缺口自动生成一张「素材待补清单」（面向用户的截图任务列表），落 `docs/research/ATLAS_GAPS_AUTO.md`，替代人肉盘点。14 个主技能 description 空、220 升级卡无独立图标、黑商全屏帧缺失都在此列。

## 硬边界

- 只动外壳层 + 本文档 + 对应测试；不碰 mediator / scenes.json / choice_policy 判定逻辑。
- 保住 `tests/test_desktop_app.py` 既有契约（负面宝物与 policy 同源、待补不编数值）。
- 图标继续用现有模板 PNG 做本机展示；不得分发原作卡面包、不得合成伪卡面。
- 提交前 `python tools/release_gate.py` 退出码 0。

## 验收

- 一致性测试绿；搜「极速」能落到「急速」（别名生效）；搜「湮灭者」详情能看到智力链与三件套实机图。
- 点击任何升级卡不会改 `settings.skills`（回归测试钉住）。
- 黑商页显示空态与待补清单。
- 回写 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`。
