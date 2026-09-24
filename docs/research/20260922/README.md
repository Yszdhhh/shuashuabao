# 2026-09-22 研究与交接快照

来源：仓外 `G:\刷刷宝\_facts_20260922\` 与 `G:\刷刷宝\handoff_prompts\`，原样复制入库（仅去掉 `__pycache__`）。代码基线 `da566dd`。
这些是**当日研究与交接记录**，不是运行配置；与代码冲突时以代码 + 测试为准，并把冲突记下来。

## 可信度分级

| 文件 | 性质 | 状态 |
|---|---|---|
| solo_strategy/DYNAMIC_SOLO_ARCHITECTURE_V1.md | 单人动态调度架构；§11 为决策契约 | 主架构认可的设计，**尚无实现** |
| solo_strategy/DYNAMIC_SIGNAL_EVIDENCE.md | 信号证据矩阵（@9ed8b52，只读） | 第一轮验收通过；**G4 宝物缺口已过时**（da566dd 已有 20 卡夹具 + 4 条新 pattern） |
| solo_strategy/SOLO_DECISION_SPEC_DRAFT.md | 单人决策规格草案（D1–D14） | 草案；多项“待 Owner 拍板”，硬阈值方向已被动态架构取代 |
| mechanics_solo/SOLO_MECHANICS_FACTS.md | 单人局内机制事实表（带证据等级与 n） | 研究资料，证据等级见各表 |
| mechanics_solo/BOSS_*.md | Boss 历史链路复核 | **撤回**旧报告“f0310 掉落弹窗 = 挑战成功”；有效结论见 BOSS_VISUAL_ACCEPTANCE 与 BOSS_POSTCONDITION_REVIEW |
| competitor/*.md | 竞品静态观察 | 竞品 ≠ 游戏事实；未经我方真机帧不得接入运行逻辑。全量分析与 1.6.2 观察的正本在 `docs/research/` 根目录（随 PR #36 入库），此处不再保留副本 |
| treasure/*.md | 宝物负面卡取证与 96 卡目录 | 已入库为 fixtures/treasure_negative |
| handoff/*.md | 当日任务单、验收记录、提示词 | 过程记录；以最新一份为准 |

## 当日 Owner 裁定（已落代码 da566dd）

- 宝物默认不拿：透支力量/贪婪献祭/金转木/杀敌梭哈/伐木契约/压制/诅咒之力/提高上限/木材梭哈，及 pattern 命中的恶魔契约/玻璃大炮/金币梭哈/贪婪契约；等级优势改为默认拿；ui-v2 全部可勾选放行。
- 蹭车：房主磨蹭不得提前转考古；考古只由局数达标 / 挑战券预算触发。
- Boss：双帧无卡只证明“停止重复定位”，不证明受理/成功（done + unconfirmed）。
