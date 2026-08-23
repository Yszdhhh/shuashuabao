# 刷刷宝 · 03_GameLogic_KB 游戏机制与底层逻辑标准交接文档 (2026-08-21)

## 一、 Agent 定位与职责边界

- **Agent 名称**：`03_GameLogic_KB`（知识库与游戏机制沉淀 Agent）
- **核心定位**：项目「游戏底层逻辑、卡牌机制、前置树、声望挑战、流派配方」的 **唯一真实来源（Single Source of Truth, SSOT）**。
- **职责边界**：
  1. 维护 `config/` 下所有结构化 JSON 知识库与规则映射；
  2. 输出人类与 Agent 友好的机制白皮书（Markdown / Word）；
  3. 为 `01_Dashboard`（UI/前端）、`05_Infra`（决策与执行状态机）提供无歧义、已验证的底层数据契约；
  4. 绝不凭空臆造数值或品质，所有数据必须有实机视频抽帧/实测截图作为佐证。

---

## 二、 核心底层知识库资产架构 (SSOT)

```
G:/刷刷宝/Worktrees/GameScript-Core02-Core03-Integration-20260816/
├── config/                                 # 结构化机器底库 (JSON)
│   ├── game_mechanics_kb.json              # 官方 7 大核心说明 (资源/热键/挑战/压力转移/胜负)
│   ├── skill_card_knowledge.json           # 16 技能族 · 220 张卡牌 (全属性/前置/互斥/品质真值)
│   ├── skill_card_catalog.json             # 技能卡标准目录字典
│   ├── skill_card_rarity.json              # 技能卡 4 阶品质映射表 (白/蓝/紫/橙)
│   ├── skill_archive_unlocks.json          # 16 技能族 · 1~40 级局外图鉴解锁表
│   ├── bond_knowledge.json                 # 羁绊体系、合成张数与三线 UR 链
│   ├── bond_stack_catalog.json             # 羁绊层数与基础分类
│   ├── reputation_factions_kb.json         # 6 大声望阵营 · 1~10 级挑战词条与 BOSS 列表
│   ├── official_strategy_defaults.json     # 官方推荐 5 大开荒/成熟流派 (Builds)
│   ├── choice_lexicon.json                 # OCR 易混淆别名字典
│   └── mode_specs.json                     # 运行模式规范 (单人刷图 / 多人跟车 / 大厅蹭车)
│
├── docs/                                   # 人类与 Agent 规范白皮书
│   ├── GAME_CORE_MECHANICS_AND_DEBUG_SPEC_20260820.md  # 游戏核心机制、公式与数值规范
│   ├── 刷刷宝_V1.0_全机制与EX副本白皮书_20260820.docx   # 局后副本、EX流派与全流程NPC流转
│   └── research/
│       ├── HERO_MODE_AND_REPUTATION_SPEC_20260821.md   # 英雄模式与 6 大声望挑战全拆解
│       └── OFFICIAL_GAME_MECHANICS_KB_20260814.md      # 游戏内置规则整理版
│
└── docs/evidence_*/                        # 实机视觉证据沉淀
    ├── evidence_cards_20260821/            # 技能图鉴、抽帧与品质比对帧
    └── evidence_reputation_20260821/       # 6 大阵营、10 级挑战词条与 BOSS 抽帧
```

---

## 三、 关键底层设计准则与铁律（新 KB 必须遵守）

### 1. 技能归属铁律：同一个图标 = 同一个技能族
- **视觉主键原则**：卡片左上角的 Icon 图标是归属的唯一主键。
  - 例如：`奥术箭矢`、`火焰箭矢` 虽带有元素/奥术前缀，但左上角均为弓箭图标，**100% 归属于【普攻（pg）】族**。
- **前置解耦原则**：联动需求纯粹记录在 `prereq: "普攻,奥术箭"` 中，绝不将联动卡错误挪动所属技能族。

### 2. 品质判别铁律：实机色框为准，未判定不判黑
- 技能品质仅有 **白 (N)、蓝 (R)、紫 (SR)、橙 (SSR)** 四种。
- 视频中暗色/置灰属于“未解锁遮罩”，绝非“黑色品质”。无确凿高亮色框的卡牌统一标记为 `unverified`（未判定），走 Fail-Closed 策略，严禁主观编造。

### 3. Fail-Forward 挂机保活准则
- **声望挑战**：选关开启英雄挑战时，若 `今日可得声望 == 0`，自动点击「取消挑战」降级为常规模式，绝不中断对局。
- **选卡决策**：3 秒未识别命中，自动触发 `_rarity_choice` 按品质盲选最高级卡牌（红UR > 橙SSR > 紫SR），绝不无限等待。

---

## 四、 核心机制字典速查（Cheat Sheet）

### 1. 16 技能族体系代号 (Family Codes)
- 普攻 (`pg`)、奥术箭 (`asj`)、奥术激光 (`asjg`)、奥术射线 (`assx`)、天雷 (`tl`)、闪电链 (`sdl`)、电磁网 (`dcw`)、火球 (`hq`)、爆炎箭 (`byj`)、寒冰箭 (`hbj`)、冰霜新星 (`bsxx`)、飓风 (`jf`)、龙卷风 (`ljf`)、剑气 (`jq`)、地震 (`dz`)、陨石 (`ys`)。

### 2. 6 大声望阵营 (`reputation_type: 1~6`)
- `1.黑锋骑士团`（力量/吸血）、`2.银色北伐军`（敏捷/物理）、`3.肯瑞托`（智力/法系 · 推荐）、`4.探险者协会`（经济/移速）、`5.元素领主`（全元素）、`6.守护巨龙`（全属性/生命）。

### 3. 羁绊三线终极 UR
- 智力线 $\rightarrow$ **【湮灭者】**；敏捷线 $\rightarrow$ **【收割者】**；力量线 $\rightarrow$ **【不动尊】**。

---

## 五、 后续工作交接与建议

1. **新 KB 扩展流程**：
   - 发现新版本词条/机制 $\rightarrow$ 提取实机录屏/截图至 `docs/evidence_*/` $\rightarrow$ 更新 `config/*.json` 机器底库 $\rightarrow$ 跑 `pytest` 和 `python tools/release_gate.py` 确保 4/4 PASS。
2. **下游协同**：
   - `01_Dashboard` 需设计新卡片或配置项时，直接引用上述 JSON 字段名（如 `reputation_type`, `auto_reputation`, `skill_preferred`），确保前后端完全对齐。
