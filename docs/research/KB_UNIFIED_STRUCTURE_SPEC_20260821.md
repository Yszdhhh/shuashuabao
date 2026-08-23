# 刷刷宝 · 游戏知识库 (KB) 统一结构规范 v2.0 — 策略驱动与功能设计指南

> **定位**：本文档是 `03_GameLogic_KB` Agent 的顶层结构规范，定义了游戏机制知识如何组织、如何驱动脚本推荐策略（choice_policy）、以及如何支撑后续 UI/功能设计。
> **更新日期**：2026-08-21
> **上游证据**：实机录屏抽帧 OCR、官方说明页截图、用户确认口述。**禁止无证据臆造数值。**

---

## 一、 KB 分层架构：证据 → 结构 → 策略 → 界面

```
┌─────────────────────────────────────────────────────────────┐
│ L0 证据层 (Evidence)                                        │
│   实机录屏 / 抽帧 OCR / 用户截图 / 官方说明页                │
│   存放: docs/evidence_*/, assets/evidence/                  │
├─────────────────────────────────────────────────────────────┤
│ L1 结构层 (Structured KB · config/*.json)                   │
│   12 份 JSON 底库（见 §二），每份单一职责，禁止开第 13 份表  │
├─────────────────────────────────────────────────────────────┤
│ L2 策略层 (Strategy · src/shuabao/choice_policy.py)         │
│   消费 L1 结构，输出选卡/选羁绊/选宝物决策                   │
├─────────────────────────────────────────────────────────────┤
│ L3 界面层 (UI · src/shuabao/shell/)                         │
│   只读 L1 字段名，渲染配置控件与状态面板                     │
└─────────────────────────────────────────────────────────────┘
```

**铁律**：任何新知识先问「归 L1 哪份文件」，再问「L2 哪条策略消费它」。禁止绕过 L1 直接硬编码进 L2/L3。

---

## 二、 L1 结构层：12 份底库职责矩阵

| # | 文件 | 职责 | 关键字段 | 策略消费点 |
|---|------|------|----------|------------|
| 1 | `game_mechanics_kb.json` | 官方机制总库：资源、热键、面板、胜负、状态效果、乘区硬顶 | `resources.*`, `hotkeys.*`, `caps.*`, `unknown[]` | 决策守卫（木头门控、F4 时机） |
| 2 | `skill_card_knowledge.json` | 220 张技能卡全量：名称/族/效果/前置/互斥/品质 | `cards[].{name,family,prereq,exclude,rarity}` | `_rank_skill_candidates` 排序 |
| 3 | `skill_card_catalog.json` | 卡名→主技能映射 + family_to_code 字典 | `family_to_code`, `cards[].family` | `expand_skill_preset_names` |
| 4 | `skill_card_rarity.json` | 卡面品质色（白/蓝/紫/橙），`unverified` 走 Fail-Closed | `cards[].{rarity, rarity_status}` | `_skill_effective_rarity_rank` |
| 5 | `skill_archive_unlocks.json` | 16 族存档等级 1~50 解锁效果（豁免前置/解锁卡） | `skills[].unlocks[].{level,payload}` | `card_unlocked_by_archive` |
| 6 | `bond_knowledge.json` | 羁绊树、三线 UR 链、合成张数 | `bond_trees`, `bond_priority`, `needs` | `_match_synthesis` |
| 7 | `bond_stack_catalog.json` | 底栏羁绊层数计数与容量 | `capacity`, `needs` | bond_capacity 决策 |
| 8 | `reputation_factions_kb.json` | 6 阵营 × 10 级挑战词条/BOSS/奖励 | `factions[].challenge_tasks_1_to_10` | 英雄模式难度选择 |
| 9 | `official_strategy_defaults.json` | 5 套官方流派：技能组合+羁绊卡组+声望推荐 | `builds[].{skills,cards,reputation_type}` | 桌面「应用流派」一键注入 |
| 10 | `choice_lexicon.json` | OCR 别名归一（奥数→奥术）、易混对、套装归属 | `entries[].aliases`, `confusions` | `_ocr_reward_choice` 规范化 |
| 11 | `mode_specs.json` | 运行模式契约：可见设置/禁用动作/预算 | `modes[].{visible_settings,forbidden_actions,budgets}` | Flow 装配与 UI 显隐 |
| 12 | `skill_meta.json` | 技能短码→中文标签、预设组合定义 | `skills`, `presets` | UI 技能网格、日志翻译 |

**单一数据源纪律**：
- 改名/别名 → 只改 `choice_lexicon`；
- 卡片效果/前置 → 只改 `skill_card_knowledge`；
- 品质 → 只改 `skill_card_rarity`；
- 等级解锁 → 只改 `skill_archive_unlocks`（走 `tools/merge_skill_archive_screenshots.py`，不手改）；
- 官方机制 → 只改 `game_mechanics_kb`。

---

## 三、 策略推荐决策管线（L2 消费路径）

### 3.1 技能选卡决策树（每帧三选一面板触发）

```
OCR 读卡名 → lexicon 归一化（奥数→奥术） → 反查 catalog 得 family
   │
   ├─ 严格模式 (4 技能已配满):
   │    候选 ∈ expand_skill_preset_names(focus_families)?
   │    ├─ 是 → 按 (前置已满足 > 角色定位 > 品质橙紫蓝白 > 等级 > 新卡) 排序 → SELECT 最高
   │    └─ 否 → 零输入等待（绝不放弃技能点），3s 后 Fail-Forward 品质盲选
   │
   └─ 填充模式 (不足 4 技能):
        safe_fill: 按品质序拿新族卡 → 凑满 4 族后转严格
```

### 3.2 羁绊选卡决策树

```
读羁绊面板 → 匹配预设白名单（bond_whitelist）
   ├─ 命中 must_take（祝福/成长/经济/贪婪/挑战）→ 必拿
   ├─ 命中属性线（智力→湮灭者 / 敏捷→收割者 / 力量→不动尊）→ 按当前 build 选线
   ├─ 未命中 → 刷新（木材 ≥40 才刷，<40 直接关闭）
   └─ 刷新 3 次无变化 → 指纹去重，关闭面板防烧木
```

### 3.3 宝物选卡决策树

```
读宝物面板 → 负面黑名单过滤（金转木/杀敌梭哈/伐木契约/透支力量/贪婪献祭）
   ├─ EX 必拿名单命中 → SELECT
   ├─ 品质排序（红>橙>紫>蓝>绿）→ SELECT 最高
   └─ 全负面 → CLOSE（绝不硬选）
```

### 3.4 英雄模式（声望挑战）决策

```
选关页 → 检测「今日可获取声望」
   ├─ >0 → 开启英雄模式 → 按配置注入 reputation_type(1~6) + level(1~5)
   └─ ==0 → 自动点「取消挑战」→ 降级常规模式（绝不卡死）
```

---

## 四、 已知缺口与补录路线图（按优先级）

### P0 — 阻塞策略精度的缺口
| 缺口 | 影响 | 补录方式 |
|------|------|----------|
| F 抽羁绊单次木头消耗未知 | 木头门控阈值（<100 不开 F）只能拍脑袋 | 实机录屏开 F 前后木头差值 OCR |
| 羁绊三选刷新单价未知 | 刷新预算（≥40 才刷）无法精确 | 同上，录刷新前后差值 |
| 16 族存档解锁缺档（剑气 2/5/7、冰霜新星 5 档、电磁网 4 档…） | 存档豁免前置排序失准 | 图鉴逐级翻页录屏 + 徽标 OCR |

### P1 — 提升上限的缺口
| 缺口 | 影响 |
|------|------|
| 力/敏/智百分比伤害递减公式 | 高属性局收益建模失真 |
| 致命一击基础倍率与命中/闪避公式 | 暴击流 vs 稳伤流无法量化对比 |
| 重创/瓦解/易伤叠乘关系 | 宝物词条估值偏差 |
| 各 EX 链中间环吞噬数（封神 6/9、亡灵 100 残骸、军团 27 吞…） | UR 进化链自动追卡缺失 |

### P2 — 长尾
- F1 恢复焦点的生效条件、F2 回基地可点范围、「打不过按 F4」的实机判定信号。
- 处理原则：**未钉死前不接线**，在 `game_mechanics_kb.unknown[]` 挂账。

---

## 五、 新功能设计接入规范（给 01_Dashboard / 05_Infra）

### 5.1 新增一个配置控件的 checklist
1. 字段是否已存在于 `default_settings.json`？存在→直接绑定；不存在→先加 L1 JSON + 默认值。
2. 该字段的合法值域与 Fail-Closed 默认值是什么？写入 `mode_specs.json` 对应 mode 的 `visible_settings`。
3. 策略层是否需要消费？需要→在 `choice_policy.py` 增加读取点 + 单测。
4. UI 文案是否需要 KB 出处？是→从 `game_mechanics_kb.json` 对应条目的 `text` 字段取官方原文，禁止 UI Agent 自编描述。

### 5.2 新增一个流派（Build）的 checklist
1. 在 `official_strategy_defaults.json` 追加 `builds[]` 条目：`id/name/skills/cards/reputation_type`。
2. 在 `skill_meta.json` 的 `presets` 同步同名条目（供看板技能网格勾选）。
3. 若涉及新羁绊组合，确认 `bond_knowledge.json` 中 `needs` 张数已钉。
4. 跑 `pytest tests -q` + `python tools/release_gate.py` 4/4 PASS 后方可提交。

### 5.3 证据入库流程
```
录屏/截图 → docs/evidence_<主题>_<日期>/ 存帧
         → OCR/人工比对 → 更新 config/*.json（带 source 字段指回帧路径）
         → 更新 docs/research/ 白皮书对应章节
         → pytest + release_gate 全绿
```

---

## 六、 当前 KB 健康度快照（2026-08-21）

| 指标 | 数值 | 状态 |
|------|------|------|
| 技能卡覆盖 | 220/220（16 族全齐） | ✅ |
| 品质确认 | 213 已证实 + 7 unverified | ✅（Fail-Closed） |
| 存档解锁 | 16 族中 11 族有缺档（见 §四 P0） | ⚠️ 补录中 |
| 声望阵营 | 6 阵营 × 10 级全量入库 | ✅ |
| 官方流派 | 5 套全量可注入 | ✅ |
| 机制 unknown 挂账 | 38 项（见 game_mechanics_kb.unknown） | ⚠️ 持续消化 |
| 测试基线 | pytest 1115 passed / gate 4/4 PASS | ✅ |
