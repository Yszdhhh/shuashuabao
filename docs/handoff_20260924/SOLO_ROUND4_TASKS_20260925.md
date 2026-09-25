# 单人第四轮任务单（2026-09-25，staff-hub 分工）

Claude 只负责拆任务、验收、纠偏；执行交给 staff-hub 外部 CLI：
`node C:/Users/10639/.claude/staff-hub/companion/agy-companion.mjs <mode> --backend <codex|opencode|omp|agy> --prompt-file <任务单>`，
在目标 worktree 目录里运行。实现类用 codex（高难度指定 `gpt-6-sol`），批量/脚本/样板用 opencode，只读分析用 agy research，审查换另一个后端。

**所有任务共同红线**：不 reset / clean / stash / force push；不改 main；不动正式版入口（桌面「刷刷宝」、`%LOCALAPPDATA%\ShuaBao\` 下任何文件，含 `current.json`、`user_settings.json`）、签名、manifest 授权链；
不改 Owner 规则锁 `tests/test_owner_ingame_rules_lock_20260924.py`；不改 `docs/baselines/GATE_BASELINE.json`（只有 T3 经 Owner 同意后可刷新）；不启动游戏、不发真实输入（T6 除外，由 Owner 操作）；外部 agent 不 commit / push，除非任务单写明。

## 当前卡点

单人实测前置是"完整门禁绿 + 快照刷新 + 测试台 SHA 更新"。门禁第二次复跑因负载红了 4 条计时/OCR 测试，按规矩停下，**等 #46 合入 fqyf7h 后，在机器空闲时跑一次，需 Owner 回"跑"**。

| # | 任务 | 执行者 | 边界（可改） | 验收标准 | 依赖 |
|---|---|---|---|---|---|
| T1 | 合并 #46 到 fqyf7h | Owner（GitHub） | — | fqyf7h 头包含 #46 全部提交 | — |
| T2 | 空闲机完整门禁 | opencode（staffer） | 只读；在默认工作根 `git switch` 到新建的 `local/quicktest-20260925` = fqyf7h 新头；只运行 `python tools/release_gate.py`，输出存 `logs/` | 退出码 0；或只剩预期差异：`scene_templates` 资产 416→429、pytest/contract 计数。有失败：每个失败 node 单跑 3 次并附 traceback，不重跑整门禁 | T1、Owner 回"跑" |
| T3 | 刷新快照 + 锚点 | Claude | `docs/baselines/GATE_BASELINE.json`（`--update-baseline --reason "09-25 蹭车实测修复：Boss 模板 55-59/21、失败横幅、背包清理模板、关卡识别"`）；锚点重钉提交 | 再跑门禁退出码 0；`pytest tests/test_live_harness_refresh.py -q` 全过 | T2 |
| T4 | 背包清理（蹭车局内 + 单人选关页）【实机通过（B1/B2）】 | agy（蹭车段进行中）→ codex `gpt-6-sol`（单人入口） | `src/shuabao/mediator.py`、`settings.py`、`config/runtime_asset_manifest.json`、`assets/Images/backpack/`、新测试与 `fixtures/backpack_clean_20260925/`、C2 `INGAME_POLLUTION` | 真实帧 g0001–g0006 回放：点击顺序 存档→装备→一键分解→是→返回游戏（单人：存档页签→…→游戏大厅页签）；传说勾上只点否；未开启/未到期/非对应模式零输入；45s 硬上限收敛；`tests/contract`、`tests/test_p1b0_post_game.py`、新测试全过；Claude 逐项审 diff | — |
| T5 | 看板开关 + "每 N 局"【代码已接，看板构建待做】 | codex | `ui-v2/src/`（开关与高级设置数字框，patch 字段 `auto_clean_backpack`、`clean_backpack_every_rounds`） | ui-v2 单测与 `tests/test_desktop_app.py` 过；按 AGENTS.md §6 构建只用 `build_release.ps1 -NoDeploy`，不动正式版桌面 | T4 |
| T6 | 测试台 SHA + READY | opencode（staffer） | 只改桌面「刷刷宝 实机测试台.lnk」参数里的 `-ProductionSourceSha` 为 T3 后 HEAD 全 40 位 | `tools/live_scenario_capture.py identity ... --json` 输出 `ready_for_gt: true` | T3 |
| T7 | 入口 12 跑两局单人（大圣 + 亡灵，看板已保存） | Owner 操作，Claude 监看 | — | 两局 trace 与 capture bundle 存在 | T6 |
| T8 | 28 条规则核对 | agy（research，只读） | 只写报告 `G:\刷刷宝\nightwatch\solo_round4_report.md` | 按 `SOLO_SCHEDULING_CHAIN_20260924.md` 顺序，每条 PASS/FAIL/NOT_OBSERVED 附 trace 行号或帧名；木材读数、插队黑商次数、吞噬丹事务、EX 识别单列；Claude 抽查 ≥5 条证据 | T7 |
| T9 | 素材 PR（大圣再临卡族标题、EX、吞噬丹事务帧） | opencode（staffer） | 新 worktree `material/live-captures-20260925`，只放 `fixtures/live_captures/20260925/` + README | `python tools/check_material_commit.py` 退出码 0；commit + push + Draft PR 指向 fqyf7h（任务单明确允许） | T7 |
| T10 | 结果回写 | Claude | `docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md` 末尾、本任务单 | 表格状态更新 | T8 |
