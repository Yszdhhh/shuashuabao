# 板块 4 · 自我学习功能（玩家画像 + 建议引擎）— 执行 Agent 提示词

> 直接把本文整份复制给执行 agent。层归属：**新模块（只读采集）+ 外壳展示**。不改 mediator 决策热路径。
> 先读仓库根 `AGENTS.md` 与 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`。

## 产品目标（用户原话拆解）

脚本能根据使用者的：
1. **技能偏好** — 进入游戏后读玩家存档里主要技能的等级（哪些系练得高 = 玩家主玩什么）；
2. **基础属性** — **一进图**按 TAB 打开属性面板，抓取装备堆叠后的进图默认盘（力/敏/智、攻速、暴击、掉宝率等）。刚入局的 TAB 不会变；打一半升级/拿卡后再抓是污染盘，不当画像。

给出**建议**（推荐流派 build、羁绊路线、宝物取舍）和**可交互的升级**（一键把建议应用为本局配置）。

## 现有底子（复用，不重做）

| 资产 | 现状 | 在本板块的角色 |
|---|---|---|
| `Settings.skill_archive_levels` + 桌面「技能存档等级」16 格 | 已接外壳，默认 `{}`=未知；`choice_policy` 传入后放宽前置/调序 | 手动输入通道保留；本板块做**自动采集**填充它 |
| `config/skill_archive_unlocks.json` | 16 系等级→解锁/减伤效果，5 系 16 档全齐 | 等级→效果的翻译层 |
| `src/gamescript/habit_preference.py` + 学习模式 observations JSONL | 已有观察记录与 `observations_to_name_scores` 聚合；决策接线未开 | 操作习惯画像的数据源 |
| `config/official_strategy_defaults.json` | 5 套 build + 三线 UR 链 + 四轮优先级 | 建议引擎的输出词表（建议=从这里选，不发明新流派） |
| `config/game_mechanics_kb.json` `basic_attr`/`special_attr` | 官方属性页字段清单（力敏智换算、硬顶） | TAB 面板抓取的字段 schema 与合法性校验 |

## 分三步交付（P0 → P2，每步独立提交）

### P0 · 玩家画像采集器（只读，零点击风险最小化）

新建 `src/gamescript/player_profile.py` + `tools/profile_scan.py`：

- **技能等级采集**：进入存档技能页（现有 L1 已能到达存档页；右下放大镜看衍生卡是官方入口），逐系 OCR 等级徽标。产出 `%LocalAppData%/ShuaBao/profile/skill_levels_YYYYMMDD.json`（系→等级→conf→截图路径）。conf 低的标 unverified，不写入 Settings。
- **TAB 属性采集**：一进图按 TAB 打开属性面板（user 2026-08-14：纯查看无副作用；user 2026-08-15：刚入局 TAB = 装备堆叠默认盘，打一半不当画像）。采集器不代按。OCR：力量/敏捷/智力/攻击/攻速/暴击/技能急速/掉宝率等。KB 硬顶（攻速 1000%、CDR 80%）超顶=OCR 错，丢弃。`classify_tab_window` 非 `entry` → 海报七格未采集。
- 全部走「截图 → OCR → 落盘 JSON」，**不产生任何写操作到游戏**。采集入口先做成测试夹 bat（模式同 `09-找房-只识别.bat` 的 dry 风格），不进主循环。
- 采集帧固化进 `fixtures/player_profile_20260814/`，README 注明分辨率与入口路径。

### P1 · 建议引擎（纯函数）

新建 `src/gamescript/advisor.py`（纯函数，输入画像 JSON，输出建议结构）：

- 规则示例（都要可在 JSON 里调）：
  - 奥术箭等级 ≥36 → 推荐 `arcane_open`，并提示「爆炸箭矢已免爆炎箭前置」；
  - 天雷/闪电链等级高 → 推荐 `thunder_classic`，附「先点审判之雷再点磁暴」的顺序提醒；
  - 敏捷属性明显高于力智 → 推荐 `aa_universal`/`sword_qi` + 收割者链；
  - 暴击率 <50% → 建议不开暴击套（对齐 `bond_trees.暴击.note`）。
- 每条建议必须带 `evidence`（画像字段值）和 `source`（引用哪份配置/KB 条目），禁止无出处建议。
- 单测：给定伪造画像，断言推荐 build 与提示语；断言画像为空时输出「数据不足，用默认」而不是瞎猜。

### P2 · 外壳交互（依赖板块 1 的 shell P0 落地后再做）

- **「个人画像」简要看板卡片**（user 2026-08-14 新增需求）：展示采集到的基础属性（力/敏/智/攻速/暴击/技能急速/掉宝率）+ 技能等级最高的几个系 + 特性摘要；未采集的格子显示「未采集」，不留空不编数。advisor 建议附在同卡片下方。
- 「智能建议」区：显示推荐 build/羁绊路线 + 一键「应用到本局」（走板块 1 已有的「应用流派」通道，写 `settings.skills/cards`，仅空闲时可用，运行中只读）。
- 应用前弹一次确认，列出将改动的技能 4 格 + 羁绊 6 格 diff。
- 习惯分（`habit_name_scores`）只做 tie-break 展示「你常拿的卡」，不自动改白名单。

## 硬边界

- 采集器**只读**。任何「读不到就点一下试试」都禁止（fail-closed）。
- 建议引擎不引入网络/云端（`do_not_auto_enable` 有「云端选卡」）。
- 不把某个号的画像写进 `config/default_settings.json`（历史教训：47 级不当全局默认）。用户画像只落 `%LocalAppData%/ShuaBao/profile/`。
- P0/P1 不碰 mediator；P2 只碰外壳层，且在板块 1 的 RunnerService/深拷贝 Settings 机制之上做。
- 提交前 `python tools/release_gate.py` 退出码 0；每步独立 commit。

## 验收

- P0：真机跑一次 `tools/profile_scan.py`，产出的 skill_levels JSON 与用户手填的存档等级一致（已知本号：奥术箭 47 / 爆炎箭 8 / 剑气 13 可当第一组真值）。
- P1：单测全绿；建议输出每条都有 evidence + source。
- P2：运行中「应用到本局」不可点；空闲应用后 `collect_settings_from_ui` 结果与建议一致。
- 回写 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`。
