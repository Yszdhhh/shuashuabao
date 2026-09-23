# 机制库收敛报告（给总架构 Agent 唯一入口）

> **日期**：2026-09-23
> **编制**：机制理解 + 测试资产盘点 + 交叉认证审查
> **当前分支**：`fix/hitch-exit-archive-fallback`，HEAD `7ebf4b2`（PR #26 以来）
> **注意**：`origin/feat/solo-shadow-scheduler-20260922` 远端存在，但本工作树不在该分支；`docs/handoff_20260923/` 整包为未提交态（`??`），同步前需按 AGENTS.md 建 topic 分支落盘，禁止直推 main。
> **阅读顺序**：本报告 → `STRATEGY_MODULE_MAP_FOR_ARCHITECT.md`（L0~L3 总图）→ `COMPETITOR_HANDOFF_CONSOLIDATED_20260923.md`（竞品唯一入口，原始 8 份备查）→ `HANDOFF_PROMPT_FOR_ARCHITECT.md`（开工 checklist）。

---

## 一、机制库基座盘点（已验证，非推演）

### 1.1 `config/` 决策真源（26 个 JSON）

| 文件 | 规模 | 本轮核验结论 |
|---|---|---|
| `game_mechanics_kb.json` | 107.7KB | 黑商 180s 免费刷新、杀敌计价、`remove_pool` 有/无区分已落；PDB/Settings 等竞品情报未进本库 |
| `choice_lexicon.json` | 114.6KB | 贪婪“随机吞4张+150木+888杀+6000金”已一致；体术仍为破甲线（见 §三.4） |
| `skill_card_knowledge.json` / `skill_card_catalog.json` / `skill_card_rarity.json` | 255.8 / 68.8 / 57.4KB | `never_pick` 仅 `蓄力射击` 1 项（已验证）；23/30/46 断崖只在研究文档，未进数值表 |
| `choice_policy.json` | 6.8KB | 宝物 `negative_names 7个` + `negative_patterns 14条`；羁绊 `base_ratio 0.8` + `advanced_unlock_s 480`；黑商 440 原子预算缺失 |
| `bond_stack_catalog.json` / `bond_knowledge.json` / `official_strategy_defaults.json` | 7.9 / 21.9 / 15KB | `gate_need=4`、`~1400木/链`一致；体术 `need=3` 与门卡 4 不冲突（不同卡） |
| `challenge_boss_catalog.json` | 7.2KB | 传家宝 `chuanjiaobao` 21 项（1–20 + 54莫阿姆），与“18 Boss”矛盾，末项疑似串项 |
| `dashboard_mechanics.json` | 25.7KB | 高级组 38 名单；体术 still `破甲10%` |
| `skill_meta.json` / `skill_routes.json` | 3.8 / 4.2KB | 未见断崖权重，需补 |

### 1.2 测试与夹具资产

- `tests/test_*.py` **123 个** + `tests/contract/` **4 个**（choice 语义/接线、L0 大厅链、C4 颜色兜底、宝物负面夹具）。
- `fixtures/reborn_wow/endgame/` 5 帧：`victory_continue / challenge_npc_hub / archive_challenge_panel / heirloom_challenge_bosses / great_rift_confirm`，支撑 `test_p1b0_post_game.py` 复合锚点判页。
- `fixtures/treasure_negative/INDEX.json` 6 名、`fixtures/treasure_must_take/`（ONEPIECE 等），支撑“7名单+描述 pattern”双冗余，但**不是** 19+2。
- 传家宝滚动已有 `test_hitch_heirloom_scroll/plaza_20260914.py`（无滚动条判定、网格指纹触底、步长可配）；压力转移门禁 `test_b15da05_real_regressions.py:163,192`；房主离场 Fail-Closed `test_s0_hitch_failure_exit.py`。
- **缺件**：`src/shuabao/solo_scheduler.py=False`（仍是 `mediator.py` 888010B 单体）；路线图点名的 7 个测试（`test_boss_challenge_20260922 / test_p0_safety_arbitration / test_treasure_negative_fixtures / test_p0_devour_failclosed / test_p1_scheduler_and_f4 / test_solo_core_development / test_policy_near_complete`）全部不存在；`config/treasure_debuff_catalog.json=False`。

### 1.3 本轮交接资产（`docs/handoff_20260923/` 7 件 + `docs/research/` 8 件未提交）

- 总图线：`STRATEGY_MODULE_MAP_FOR_ARCHITECT.md` + `HANDOFF_PROMPT_FOR_ARCHITECT.md`。
- 竞品线：`CROSS_AUDIT_DOSSIER_20260923.md`（Gemini 3.8 Flash 卷宗）+ `COMPETITOR_HANDOFF_CONSOLIDATED_20260923.md`（独立审计整合，**与原文冲突以本文件为准**）+ `COMPETITOR_KNOWLEDGE_INDEX.md` + `HANDOFF_PROMPT_FOR_AUDITOR.md` + `HANDOFF_PROMPT_FOR_COMPETITOR_ANALYST.md`。
- 8 份 `docs/research/COMPETITOR_*_2026092*.md` 为未提交态，只读静态、未跑竞品 EXE、`src/` 零触碰（红线已守）。

---

## 二、收敛裁决（Confirmed / Conditional / Rejected）

### 2.1 Confirmed（可直接用）

1. **L0 双模掩码方向**：20s 压力转移先于自动任务、房主离场 Fail-Closed、战后复合锚点（`continueGame / damijing+HeroChallenge / archiveChallenge / cjbtiaozhan / mijingOk+ok`，禁单凭顶部 HUD）。
2. **技能红线**：`≤4系` + `蓄力射击 never_pick` + `allow_skill_giveup=False`。
3. **羁绊基线**：`gate_need=4`、`~1400木/链`、`base≥80% + 同时只推1套高级组`。
4. **宝物双冗余思想**：名单（贪婪献祭/等级优势等描述无特征项）+ 描述子串，两路互备。
5. **黑商基线**：杀敌计价 + 180s 免费冷却 + 只收敛吞噬丹。
6. **贪婪套装语义**：“散件收益之和 + 套装随机吞4张可吞食卡”，`bond_knowledge / lexicon / dashboard` 三源一致。
7. **竞品三栏红线**：拒抄暴力三连 ESC/绝对坐标/`Y+40` 盲点；REJECT 关闭 Defender 与签名遮蔽（仅借鉴合法 Vault 思想）。

### 2.2 Conditional（可用但需真机标定，勿直接进 production）

1. **脚本1 Settings 是 78 项不是 74 项**：以 `COMPETITOR_HANDOFF_CONSOLIDATED §5` 纠偏为准，原“74项”表述作废，默认值需重标（`FollowTheLead / AutoCloseMainLine / NewRoomEveryTimes / SmallCJBoss 1/2/3 / OnlyTransfer`）。
2. **1.6.3 增量**：海贼王 `haizeiwang/haizeiwangEx` ≠ 海盗羁绊；`buguimijing` 不归秘境独立判页；三极卡（力/敏/智之极）；PDB 数字待重填。
3. **落地三项新设计**：业务令牌看门狗（300s 零推进熔断，恢复单 ESC）、18 网格虚拟滚动（可视 4–5、`NumberOfScroll` 1–4、禁右键）、3/4 选一几何（`Xi` 公式 + OCR 收束安全区 + 卡片下沿 `Y+35px` 热区）。
4. **传家宝分层**：吸纳 `SmallCJBoss` + `room_heirloom_bosses[3]`，按阶段/按房隔离（前期 15 猛虎之神 → 后期 39 拉格纳罗斯/21 界龟），需两帧标定。
5. **P0 图鉴缺口**：21 界龟、55 吞咽者布鲁、56 狩猎者阿娅米斯、57 无疤者奥斯里安、`mingyuntouzi` 命运骰子、`emptyArtifact` 空槽，先放 `staging/`，两帧对比后入库。

### 2.3 Rejected / 冻结（不得按原文施工）

1. **体术“斗气场域 80% 力量伤”推翻**：机制库四处仍为破甲 10%/need=3，无卡面 OCR 帧支撑。在补帧前冻结为现状，标 `needs_live_check`，不得改目录。
2. **“19+2 默认拦截已落地”**：落盘仅 7 名 + 14 pattern + 6 夹具名，`treasure_debuff_catalog.json` 缺失。先建单源再谈拦截。
3. **STALLED `>2500木` 可直接用**：与现行 `advanced_unlock_s=480s` 时间兜底是两套退出条件，未统一。统一为 `(耗木>2500 ∧ 停滞) ∨ (t>480s ∧ base<80%)` 后再落地。
4. **440 原子预算已落地**：`rg 440` 零命中，需新建。
5. **`solo_scheduler` 纯函数已落地**：文件不存在，需新建；mediator 单体不动存量行为。

---

## 三、给总架构的 P0→P1→P2（验收口径：PASS / CONDITIONAL / REJECT + 真机两帧）

**P0（安全底线，任一 FAIL 停发）：**
- P0-1 宝物单源：新建 `config/treasure_debuff_catalog.json`（全量 + `DESCRIPTIONS.json` 帧号），`choice_policy` 只读它；补缺失的负面单测。
- P0-2 黑商原子预算 + 180s 计时器（含 410 拒绝 / 440 放行边界）；采样失败沿用脚本3 `999` 语义（永不误判资源尽）+ 像素哈希否定证据。
- P0-3 贪婪防误吞锁 + 木材快照预算（禁 `Wood_{t+1}≥Wood_t` 假设）；补 `test_p0_devour_failclosed.py`。
- P0-4 图鉴 staging：§2.2 之 P0 缺口 + 莫阿姆串项核查，不入 `assets/` 生产目录。

**P1（状态机与几何鲁棒）：**
- 高级组统一退出状态机 OPEN/ACTIVE/STALLED/FINISHED；`solo_scheduler.py` 纯函数拆出（mediator 只执行）；`Xi` 几何 + 传家宝网格禁右键断言；战后 `Action Lease` 若引入必须先过 `test_p1b0_post_game.py`。
- 吸纳 `NewRoomEveryTimes`（防 >10h 句柄卡死）、`OnlyTransfer` 纯工具人、`CaptureWin` 失败落包、飞书 Webhook（节流）。

**P2（实验档）：** ONEPIECE 跨品质保底、多房传家宝、Vault 双轨打包、OTA 指纹轮询。均需 A/B + 两帧后转正。

**全程红线**：`python tools/release_gate.py` 归零；一次一层提交；C2 局内污染隔离 + C4 禁颜色兜底；UNKNOWN 零输入 Fail-Closed；禁合成帧冒充真机；竞品 EXE 只读不跑；`src/` 改动权只归总架构（分析/审计线禁碰）。

---

## 四、待采证据清单（堵住“推演当事实”）

1. 体术卡面两帧（名 + 描述 + 数值）→ 裁定破甲 vs 斗气。
2. 木材突发扣除帧（前后余额同框）→ 快照预算参数。
3. 高级组卡手局（耗木>2500 + 零推进）→ STALLED 阈值。
4. 传家宝 18/21 对账（可视 4–5 + 滚动 1–4 + 末项莫阿姆）→ catalog 正名。
5. 1.6.3 九图（海贼王/不归秘境/三极卡）时间戳 + 两帧 → staging 转正。
6. `Settings.cs` 78 项重标 + PDB 数字重填 → 关闭 CONDITIONAL。
