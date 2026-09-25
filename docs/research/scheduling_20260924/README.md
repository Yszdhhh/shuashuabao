# 局内调度量化调研（2026-09-24）

目标：把主线（F 羁绊、G 技能）和支线（宝物、每 5 级点击进化、黑商 / 吞噬丹、物品栏、神器）穿插时的阈值，从凭直觉给的数改成有数据支撑、能校准的规则。本目录只放调研材料和设计输入，不改生产行为。

## 本目录文件

| 文件 | 用途 |
|---|---|
| `ASSESSMENT_AND_FRAMEWORK.md` | 云端评估：现有资料够不够、需要校准的阈值清单、量化框架、trace 需要记录的字段 |
| `GPT_DESK_RESEARCH_PROMPT.md` | 给 GPT 的完整调研任务：案头调研 + 竞品调度拆解 |
| `LOCAL_DATA_COLLECTION_PROMPT.md` | 给本地 agent 的补采任务：竞品反编译局内循环、已有日志统计、缺的截图 |
| `gpt/` | GPT 的产出（由 GPT 的 PR 新增） |
| `local/` | 本地 agent 的产出（由本地 PR 新增） |

## 外部协作者（GPT）的阅读范围

分支：`claude/project-thread-fqyf7h`（main 落后，不要读 main）。

**必读**
- `AGENTS.md`（硬规矩）
- 本目录 `ASSESSMENT_AND_FRAMEWORK.md`、`GPT_DESK_RESEARCH_PROMPT.md`

**只读参考（可以引用，不要修改）**
- `docs/research/`：`EX_SYNTHESIS_CHAINS_10EX_20260923.md`、`CARD_FAMILY_FINE_MECHANICS_20260923.md`、`TREASURE_EXTERNAL_GUIDE_REVIEW_20260923.md`、`GUIDE_PIRATE_AND_HAIZEIWANG_20260923.md`、`COMPETITOR_*.md`
- `docs/handoff_20260923/`：`STRATEGY_MODULE_MAP_FOR_ARCHITECT.md`、`MECHANISM_CONVERGENCE_REPORT_FOR_ARCHITECT_20260923.md`、`COMPETITOR_HANDOFF_CONSOLIDATED_20260923.md`
- `config/game_mechanics_kb.json`（`resources`、`refresh_ledgers`、`unknown`）、`config/choice_policy.json`、`config/official_strategy_defaults.json`、`config/bond_stack_catalog.json`
- `src/shuabao/mediator.py`（`_solo_plan_panel`、`_l1_step_visit_exhausted`、`_L1_CYCLE_ORDER` 附近）、`src/shuabao/solo_scheduler.py`、`src/shuabao/observe_log.py`、`src/shuabao/bond_capacity.py`

**不用读**：`docs/` 下其余按波次堆叠的历史文档（B0–B10、N/S/O/P/G/R），多数已过期、互相矛盾，以上面列出的为准。

## 产出放哪

| 谁 | 分支 | 产出目录 | PR |
|---|---|---|---|
| GPT | `gpt/<主题>-<日期>`，例如 `gpt/scheduling-research-20260924`，从 `claude/project-thread-fqyf7h` 拉出 | `docs/research/scheduling_20260924/gpt/` | Draft PR，目标 `claude/project-thread-fqyf7h` |
| 本地 agent | `research/scheduling-calibration-20260924` | `docs/research/scheduling_20260924/local/` | Draft PR，目标 `claude/project-thread-fqyf7h` |

## 红线

- 产出只作设计输入。不改 `src/`、`config/`、`tests/`，不改任何生产默认值；改阈值要另外立项、单独提交、过 `python tools/release_gate.py`。
- 不删改 Owner 规则锁测试 `tests/test_owner_ingame_rules_lock_20260924.py`。
- 数值必须标来源等级（`live` / `guide` / `inferred` / `none`），没有来源不要编；和实机记录冲突时并列，不覆盖。
- 不推荐"卡住就连按 ESC"、盲点固定坐标、颜色兜底进房，也不能用合成图冒充实机证据。
