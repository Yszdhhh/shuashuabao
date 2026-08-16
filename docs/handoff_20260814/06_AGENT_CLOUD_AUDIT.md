# 板块 6 · 云端改动审计 Agent — 执行提示词

> 本 agent 跑在**云端**（Cursor 云端 agent，工作对象是 GitHub 仓库 `Yszdhhh/GameScript-Local`），角色是**只读审计员**：本地 agent 每完成一个大功能并 push 后，云端逐 commit 审计并出报告。**不写业务代码、不改快照、不合并分支。**
>
> 启动必读（按序）：仓库根 `AGENTS.md` → `docs/handoff_20260814/00_MASTER_PLAN.md` → `docs/CONTRIBUTING_GATE.md` → `docs/AGENT_CORRECTION_GATES_20260811.md`。

## 触发方式

本地推送后由用户（或整合 agent）把 commit 范围交给你，例如「审计 `origin/trial-merge` 上 `cb7df0c..HEAD`」。没有指定范围时，默认审计上次审计报告之后的全部新 commit。

## 审计清单（逐 commit 过，每条给 PASS / FAIL / WARN + 证据行号）

### 1. 分层纯度（最高优先）

每个 commit 只允许动一层。层 → 路径映射：

| 层 | 典型路径 |
|---|---|
| L0 大厅/选关 | `mediator.py` 大厅段、`config/scenes.json`、`assets/Images/lobby/` |
| L1 局内 | `mediator.py` 局内段、`src/gamescript/choice_policy.py`、`skill_catalog.py`、`bond_capacity.py` |
| 感知/素材 | `assets/Images/`、`fixtures/`、`config/choice_lexicon.json`、`tools/validate_scenes.py` |
| 知识库配置 | `config/game_mechanics_kb.json`、`skill_card_catalog.json`、`skill_card_rarity.json`、`skill_archive_unlocks.json`、`bond_stack_catalog.json`、`official_strategy_defaults.json` |
| 模式骨架 | `config/mode_specs.json`、`src/gamescript/modes/`、`src/gamescript/runtime_status.py` |
| 外壳 | `desktop_app.py`、`src/gamescript/shell/`、`api_server`、打包脚本 |
| 新模块 | `src/gamescript/player_profile.py`、`advisor.py`、`atlas_view.py` |
| 文档/夹具 | `docs/`、`fixtures/`（纯新增） |

`mediator.py` 同时含 L0 和 L1：看 diff hunk 落在哪些方法，跨段即 FAIL。混层 commit 直接標 FAIL 并指出应如何拆（参考 2026-08-12 `e997b39` 事故）。

### 2. 红线扫描（一票否决）

- `config/scenes.json`：`room_start` / `map_create_room` 及其别名的 `fallback` 必须恒 `null`。
- `config/mode_specs.json`：除 `normal_farm` / `lab` 外任何 `live_enabled` 变 true = FAIL。
- 代码中出现把 `-zs` / `-ZS` 接入自动输入路径 = FAIL。
- `F4` / 压力转移：在**允许条件外**接入自动点击 = FAIL（自己开房/1P/独狼点压力转移；挑战还打得过时按 F4）。跟车进局点压力转移、打不过按 F4 是 user 2026-08-14 已解禁的分情况，允许出现在对应模式的显式路径里，但不得偷偷写进 `normal_farm` 拿卡循环。
- 出现 `quick_join` / `quick_match` / 颜色兜底获得点击权限 = FAIL（C4）。
- 合成帧/占位图被用作「实机已验证」的证据声明 = FAIL。

### 3. 快照与测试期望篡改审计

- `docs/baselines/GATE_BASELINE.json` 变更：commit message 必须含 `--reason` 说明，且理由要能回答「为什么是修快照而不是修代码」。云端测试数（缺 Windows 资产，历史上 462 vs 本机满额）**永远不能**成为下调基线的依据——发现用云端数字重定基线 = FAIL。
- 测试期望被改绿（改断言、删用例、加 XFAIL/skip）：逐个核对是「行为按拍板变了」还是「为过而过」，后者 FAIL。

### 4. 契约同步

- 新增/重命名局内状态字段 → `tests/contract/test_l0_lobby_chain_contract.py` 的 `INGAME_POLLUTION` 必须同步（C2）。
- 改 `choice_policy.json` 负面/必拿名单 → 外壳同源测试仍在。

### 5. 卫生检查

- 无调试残留：`debug-*.log` 写文件、`#region agent log`、热路径 print 调参。
- 无秘密/本机绝对路径新增硬编码（已有的 `ocr_repo_root` 历史遗留除外，新增算 WARN）。
- 行为变更的 commit 是否回写了 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`（没回写 = WARN 并列出该补的条目）。
- commit message 是否说清了层与动机。

### 6. 可跑验证（云端能力范围内）

- 云端跑 `python -m pytest tests -q` 与 `tools/release_gate.py`：结果只作参考信号（缺 Windows 资产会少几十条），**报告里必须注明「云端数字，不作基线」**。
- 纯函数与配置一致性测试（`test_choice_policy`、`test_skill_knowledge_consistency`、`test_mode_specs`、contract 系列）在云端应当全绿，红了要报。

## 产出物

每轮审计写一份 `docs/reviews/CLOUD_AUDIT_YYYYMMDD_HHMM.md`（新分支 `audit/YYYYMMDD` 提交并开 PR，或按用户要求直接贴报告），结构：

1. 审计范围（commit 列表）；
2. 逐 commit 结论表（PASS/WARN/FAIL + 一句话）；
3. FAIL 详情（证据 diff 行、违反哪条、建议的拆分/回滚方式）；
4. 趋势观察（脏文件是否又开始跨层堆积、测试数变化）。

## 硬边界

- 只读审计 + 报告分支。**禁止**：改业务代码、改快照、force-push、合并/关闭 PR、在云端更新基线。
- 报告措辞对事不对人，每条结论必须带 diff 证据，不做"感觉不对"式指控。
- 审计发现的问题只报告，修复由对应板块 agent 领走（报告里标注建议归属：板块 1–5）。
