# 给 GPT 的案头调研提示词（直接整段复制）

---

你是一名游戏机制分析师兼自动化调度设计顾问。请帮我做一次**案头调研**，目标是把一款游戏自动化脚本的"局内调度"从拍脑袋的阈值改成可以量化、可以校准的规则。你只做研究和设计，不写生产代码。

## 背景

- 游戏：KK 对战平台上的 War3 自定义地图《重生魔兽刷刷刷》（刷怪、抽卡构筑、合成类）。
- 项目：刷刷宝，一个 Python 写的自动化脚本。流程是截图、OpenCV 模板匹配和 OCR 识别，再用真实点击操作。公开仓库：https://github.com/Yszdhhh/shuashuabao
- **请读分支 `claude/project-thread-fqyf7h`**（最新统一版），不要读 main（main 落后）：https://github.com/Yszdhhh/shuashuabao/tree/claude/project-thread-fqyf7h
- 局内资源和动作：
  - 木材：F 抽羁绊、刷新羁绊三选都花木材。
  - 技能点：每升 1 级得 1 点，按 G 抽技能。技能点无上限、不过期。
  - 杀敌数：黑商付费刷新和购买都花它；黑商每 180 秒有 1 次免费刷新。
  - 刷新次数：宝物、技能、英雄卡三选的刷新次数只来自宝物词条或局外效果卡。
  - 支线：V 宝物三选、每 5 级一次的点击进化、黑商（尤其是羁绊栏快满时买吞噬丹腾格子）、物品栏（吞噬丹、道具、英雄卡）、神器（Q/W/E，冷却约 120s）。
- 痛点：现在的调度规则都是负责人凭直觉给的数，例如"木材 <500 且技能积压时先点技能"、"基础羁绊完成 80% 才开始推高级组"、"羁绊栏占 8/10 格就去黑商找吞噬丹"、"木材 ≥1000 时 F 每次拿 15 张"。这些数不科学，也没法量化。
- 最大的难点：脚本**读不到战力值**（攻击、DPS 都读不到），只能读到木材、杀敌余额、技能点角标、宝物角标、主线关卡号、羁绊栏占用。

## 先读这些文件

1. `AGENTS.md`（项目硬规矩，尤其"不确定就零输入等待"和"禁止用合成帧冒充实机证据"）
2. `docs/research/EX_SYNTHESIS_CHAINS_10EX_20260923.md`（合成链，以及技能、黑商、宝物怎么穿插）
3. `docs/research/CARD_FAMILY_FINE_MECHANICS_20260923.md`
4. `docs/handoff_20260923/STRATEGY_MODULE_MAP_FOR_ARCHITECT.md`（L0–L3 决策分层、黑商两段式预算、高级组停滞熔断）
5. `docs/handoff_20260923/MECHANISM_CONVERGENCE_REPORT_FOR_ARCHITECT_20260923.md`
6. `docs/research/COMPETITOR_SCRIPT1_SETTINGS_MAP_20260923.md`、`docs/research/COMPETITOR_FULL_ANALYSIS_20260922.md`、`docs/research/COMPETITOR_STATIC_OBSERVATIONS_SCRIPT3_20260923.md`（竞品）
7. `config/game_mechanics_kb.json`，重点是 `resources`、`refresh_ledgers`、`unknown` 三段（已知 / 未知的单价）
8. `config/choice_policy.json`、`config/official_strategy_defaults.json`、`config/bond_stack_catalog.json`
9. `src/shuabao/mediator.py` 里的 `_solo_plan_panel`、`_l1_step_visit_exhausted`、`_L1_CYCLE_ORDER` 附近（当前调度规则和常量），以及 `src/shuabao/solo_scheduler.py`（已写好但只以 shadow 方式运行的纯函数调度器）
10. `src/shuabao/observe_log.py`（现有观测日志记了哪些字段）
11. `src/shuabao/bond_capacity.py`（羁绊栏容量不变量：自由度 = 空槽 + 吞噬丹）

另外，先读本目录的 `README.md` 和我方评估 `docs/research/scheduling_20260924/ASSESSMENT_AND_FRAMEWORK.md`。

## 请回答

**A. 公开资料里的经济数值**
搜索 B 站、抖音、贴吧、KK 论坛、QQ 群公开整理里关于《重生魔兽刷刷刷》的攻略，找以下数值，每条都要注明来源链接和发布日期：
- F 抽羁绊的木材单价及随次数的递增规律；羁绊三选刷新的木材单价
- 各阶段木材收入速率（主线挑战奖励、击杀、经济类羁绊）
- 黑商各商品的杀敌价（尤其吞噬丹）、付费刷新价、商品出现概率、黑市等级影响
- 升级速度（经验曲线）和每 5 级进化的收益
- 基础羁绊（力 / 敏 / 智门卡链）成型后的属性跳变；高级组（封神、神兽、异火、刀刀、海盗、亡灵等）成型的平均耗木和耗时
- 技能各系的质变等级（我方只知道奥术箭 23 / 30 / 46 级）
- 高手的开局节奏（前 10 分钟先做什么、何时开高级组、何时停抽）

没有来源的数字请标"无来源"，**不要编**。和我方已记录的实机数值冲突时，两者并列写出，不要覆盖。

**B. 竞品调度思路**
根据仓库里的竞品文档，推断脚本1（GameScript）局内主循环大概怎么排（哪些动作按优先级、哪些按定时器、资源门槛是多少）。标清哪些是文档原文、哪些是你的推断。再说说哪些思路值得借鉴，哪些只是"换一组拍脑袋的数"。

**C. 量化调度框架评审**
评审我方的思路：把每个动作看成"花瓶颈资源换战力"，每个 tick 选单位瓶颈资源换来战力最多的动作，战力用"主线每关通关秒数、主线停滞时长、杀敌速率、到 5-5 的时间"间接衡量。请回答：
- 这个框架有什么漏洞（例如随机性、长期回报、卡池稀释、合成周期）？
- 有没有更合适的形式化方法（例如影子价格 / 边际价值、多臂老虎机、强化学习里的 reward shaping、简单的规则 + 参数扫描）？请按"实现成本低、数据要求少"优先推荐，说明各自需要多少局数据。
- 对这些阈值，逐条给出应该用什么数据、什么方法来校准：500、1000、300、80%、480s、每组刷新 2 次、羁绊栏 8 格找丹、黑商 440 预算、技能积压 4。

**D. 实验设计**
给出一个本机能执行的 A/B 实验方案：分几组、每组多少局、控制哪些变量（英雄、难度、地图版本）、看哪些指标、怎么判定显著。考虑到每局约 15–30 分钟，总预算控制在 60 局以内。

**E. 长时间运行兜底**
我方已有：单局 3600s 硬超时、主线 idle 看门狗、15s 无进展看门狗（只撤输入、不按 ESC）、每局新建房、失败取证包。缺：业务进度看门狗、跨局健康统计、通知。请结合竞品和通用挂机脚本的做法，列出连续跑 8–10 小时最常见的失败模式和对应的检测信号。**不要推荐"卡住就连按 ESC"或盲点固定坐标**，我方明确禁止。

## 输出要求

- 在分支 `gpt/scheduling-research-20260924`（从 `claude/project-thread-fqyf7h` 拉出）提交一个 Markdown 文件：`docs/research/scheduling_20260924/gpt/SCHEDULING_QUANT_DESK_RESEARCH_20260924.md`，然后开 **Draft PR，目标分支 `claude/project-thread-fqyf7h`**。不能推分支时，把整份文件内容直接回给用户。
- 简体中文，结论写在最前面。结构：结论 → A → B → C → D → E → 来源列表。
- 每个数值都要有来源等级：`live`（实机截图 / 录屏）、`guide`（公开攻略）、`inferred`（你的推断）、`none`（无来源）。
- 表格优先，每节不超过两屏。
- 这份产出**只作为设计输入**：只提交 `docs/research/scheduling_20260924/gpt/` 下的文件，不改 `src/`、`config/`、`tests/`，不删改 Owner 规则锁测试 `tests/test_owner_ingame_rules_lock_20260924.py`，不给"直接把某常量改成某值"的结论，只给"用什么数据、怎么验证后再改"。
