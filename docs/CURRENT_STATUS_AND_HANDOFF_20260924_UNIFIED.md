# 统一版本交接（2026-09-24）

## 组成

`claude/project-thread-fqyf7h` 分支上的统一版本，由三部分组成：

1. PR #37（`fix/desktop-sync-20260923`，头 `1b0a1a8`）。它已经包含 PR #36 的前 125 个提交（两者分叉点是 `94f5023`）。
2. PR #36 在 `94f5023` 之后的独有提交：
   - 直接叠上：`985d350` `d5d7107` `5fcb253` `661773a` `c3f42f5` `e5838f5` `6b9bf9e`。
   - 已在 #37 里，跳过：`7f847c2` `3ecd095` `6717cad`。
   - `3f4f9af`：取 #37 这一侧解冲突后没有剩余改动，说明它的内容已被 #37 的 `8a0f02e` 和 `f082f0a` 覆盖，因此跳过。
   - `533e7b5`（UI-24 看板）：在 `ui-v2/index.html` 上有 3 处冲突。日志条保留 #37 的高度过渡动画；龙珠图标和负面宝物手风琴采用 UI-24 的写法。
3. `fix/launch-summary-escape-20260913` 的两个 XSS 转义提交：`9f60c97` 和 `4519970`。

所有原始提交都保留，合并时用 merge commit，可以二分定位。

## 未完成，需要在本机做

- `python tools/release_gate.py`：云端 Linux 缺 Qt 和 OCR venv，只能跑部分 pytest，不能算门禁 PASS。确认 failed=0 后，再用 `--update-baseline --reason` 更新 pytest 计数。
- 身份锚点：`config/runtime_identity_manifest.json` 仍指向 `94f5023` 一系的候选。合入 main 后，需要补一个锚点提交，指向合入后的 HEAD。
- `build_release.ps1` + `release_harness.py`，并核对桌面 `build_identity.json` 的 `source_sha`（AGENTS.md §6）。
- 需要重新真机验证：蹭车→考古交接和局数计数（`f082f0a`）、Boss 点击后确认、宝物负面默认不拿、#37 的满槽顶替和 F1 兜底、银月之晶、UI-24 看板（含上面 3 处冲突的取舍）、启动摘要转义。

## Owner 2026-09-24 决策修正（7 个提交，叠在本统一分支之上）

Owner 2026-09-24 三条决策加审查发现的问题，按层分成 7 个提交，都未经真机验证：

- 感知：技能面板改点真正的【刷新(N)】按钮（通用 `refresh`）。`skill_refresh_btn` 是「技能免费刷新次数+1」文字截图，命中点压在【放弃】上沿。bond/treasure 恢复"专用钮优先"的顺序查找（`1b0a1a8` 曾改成全面板取最高分）。契约 `test_skill_refresh_btn_priority_contract.py`、冻结回放 `giveup_panel_not_fail` 的期望已按真帧改正。`select_hero.png` 已登记进运行资产清单。
- L1 调度：木材 < 500 且有技能积压时先点技能；木材 ≥ 1000，或基础羁绊未成型且木材 ≥ 500 时先点羁绊。500 是 Owner 给的初值，要在实机上调。木材低时宝物恢复在自己那一步打开。`RuntimeMediator._bond_presets_complete` 恒为 False，拿齐预设后不再整局跳过或关闭 F。
- L1 选卡：本页出现还没拿到的预设基础羁绊时，先拿基础羁绊，排在"差一张合成"之后；已经起步的高级卡组（持有同组卡）不受影响。80% 基础完成比例未改，待实机调。
- L1 英雄焦点：看板丢失时按 F1。【▲选择英雄】提示改到面板已关、局内 HUD、提权和 dry_run 这几道门禁之后才处理。
- 恢复与战后：新增战后画面飞离广场时按 F2（`_maybe_recover_post_game_view`）。触发条件是顶栏仍为「存档」广场模式、两个不同帧间隔 ≥2s 都认不出战后页面，每 8s 最多一次，每个战后事务最多 3 次。局内画面飞走还没有检测信号，需要实机帧。
- L1 满槽顶替：OCR 改用真实接口 `shadow_predict`（原来调用的 `predict_sync` 不存在）。只点 OCR 认出、且不是目标合成卡组也不是刚拿的同名卡的槽位，认不出就零输入。
- L0 蹭车：QUIT 落到房主选难度页时，只要处于蹭车模式就发一次语义 Esc。

云端门禁（Linux）：冻结回放 PASS（6 PASS、1 BLOCKED 断线素材），contract 67 PASS。scene_templates 只剩资产数量 404→405 与快照不一致，这是有意新增的 `select_hero.png`。pytest 有 8 个桌面/发布模块因缺 Qt/EGL 无法收集。快照没有在云端刷新（刷新必须跑全阶段，云端 pytest 不完整），需要在本机跑 `python tools/release_gate.py --update-baseline --reason "select_hero.png 资产 + 技能刷新真按钮期望纠正"`。

需要真机验证：木材 20~1000 区间技能/宝物是否还会被饿死；基础羁绊优先后高级卡组的成型时间；【▲选择英雄】的触发场景；战后 F2 的触发与回广场效果；满槽顶替 OCR 在卡槽栏上能否读出卡名（读不出就不会顶替）；蹭车选难度页 Esc 后能否回到房间。
仍在 main 上能过、统一分支上失败的测试（与本节修正无关，待逐条定性）：`test_b15da05_real_regressions`（5 条，蹭车平台弹窗关闭顺序）、`test_live_scenario_capture`（2 条）、`test_card_template_bidirectional`（2 条，`545b20f` 登记了 `dashengzailin`/`haizeiwang` 标签但缺 `cards/*.png`）、`test_policy_near_complete_and_treasure_safety`（满槽允许核心卡，`7751495` 的有意改动，测试期望未跟上）、`test_solo_gt_regression` 白名单外债务、`test_solo_planner` 首帧秒选、`test_solo_b2_pickup_speed`、`test_s0_safety_state_machine` 面板可见性、`test_live_run_205044` 低置信二帧、`test_solo_main_line_close_task` 5-6 关闭任务、`TestSafetySweep`（超时）。另有 3 条身份锚点断言。

## 分支收敛

远端分支清单和删除建议见项目文件 `branch_convergence/分支收敛方案_20260924.md`。统一版本合入后，#36、#37 关闭，被吸收的分支按清单删除。
