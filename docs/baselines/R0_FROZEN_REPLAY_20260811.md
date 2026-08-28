# R0 冻结端到端回放集（R0-FROZEN-REPLAY，1600×900）

> 日期：2026-08-11　分支：`codex/ocr-hybrid`　基线：db73fd9（场景契约验证时 HEAD）
> 依据：docs/SCOPE_OVERRIDE_1600X900_20260811.md 即时指令第 5 条
> （“用现有 1600×900 录像和面板素材建立冻结的 end-to-end 回放集”）与
> docs/baselines/R0_REPLAY_GAP_20260811.md（G1-G5 缺口 / F1-F9 建议）。
> 范围：`fixtures/baselines/replay_frozen/` + `tools/run_frozen_replay.py` + 本文档
> （R0-FIX 所有权；与 O4-FIX/OCR-BLIND 文件互不重叠）。

## 1. 结论

- 六类场景（fail+panel / giveUp+panel / 存档挑战 / 主线 HUD / stage / 退出确认）以**真实
  Mediator.tick()** 冻结运行，全部 PASS；
- 断线场景真实素材缺失，**如实 BLOCKED**（不伪造，与 O3 missing_disconnect_modal 一致）；
- off/shadow 双模式 ledger diff = 0（12 行 × 2 模式），覆盖含动作场景 ≥2 个（全部 6 个）；
- 全部帧为仓库既有素材**引用**（零新采集、零缩放伪造）；输入全部经 FakeInputExecutor 记账，
  dry_run=True，不产生真实游戏输入；960×540 不涉及。

## 2. 回放集结构

```
fixtures/baselines/replay_frozen/
  manifest.json                    # 场景清单 + 帧来源 + ledger 预期 + 缺失声明
  scenes/
    fail_panel_preempt/case.json     # R0.1-#1 fail+panel 抢占
    giveup_panel_not_fail/case.json  # R0.1-#2 giveUp+panel 非失败
    archive_challenge_open/case.json # R0.1-#3 存档挑战零动作
    main_hud_idle/case.json          # R0.1-#4 主线 HUD（进化点击 + idle）
    stage_select_scroll/case.json    # R0.1-#5 选关页有界滚动
    exit_confirm_quit/case.json      # R0.1-#6 退出确认 → 回房
tools/run_frozen_replay.py          # 统一运行入口（tick 级 + ledger + off/shadow diff）
```

case.json 复用 `tests/test_scenario_replay.py` 的 schema（schema_version 1）：每帧声明
phase_before/context/action_count/action/action_result/phase_after/loop_action + final_phase；
帧路径为仓库内相对引用（帧引用而非拷贝）。

## 3. 场景契约（每场景：输入帧序列 → 断言 → ledger 预期）

| scene_id | 输入帧（真实素材） | 关键断言 | ledger 预期（frame 级） |
|---|---|---|---|
| fail_panel_preempt | d0_a_002238.png ×2 + d0_a_002694.png（rec9_mijing idx_a 帧 002238/002694，fail 模板 0.916/0.956 + 面板锚点并存） | f1 零动作（FAIL 候选）；f2 两帧抢占 → RECOVER_FAILURE，选卡输入=0；f3 RECOVER_FAILURE 零输入等待（ok 模板本帧无命中，不消耗尝试） | 3 行：none/none；RECOVER_FAILURE none；RECOVER_FAILURE none |
| giveup_panel_not_fail | giveup_panel.jpg（idx_b 000105，giveUp 0.926 + 技能面板锚点）→ idle_hud.png（面板关闭） | f1 AMBIGUOUS_GIVEUP：非失败、不进恢复、继续面板 FSM（点 bond rarity_red @864,359）；f2 面板 episode 干净结束，零输入 | 2 行：left_click [864,359]（bond选择）；none |
| archive_challenge_open | archive_challenge_panel.png（1596x921，ARCHIVE_PANEL） | 零动作；非胜利链路进存档面板触发 Fail-Closed 守卫（incident，dry-run 恢复 MAIN_LINE） | 1 行：none |
| main_hud_idle | main_line_auto_on.png（1609x932，idle HUD 无面板） | f1 点击进化（click_evolve 0.982 @525,810）；f2 5s 进化冷却内 idle 零输入 | 2 行：left_click [525,810]（ClickEvolve）；none |
| stage_select_scroll | stage_select.png（1600x900，选关页） | 目标关卡不在可见列表 → 有界滚动（scroll @1080,468,-1，0.8s 冷却；共 2/8），绝不点击列表外关卡 | 2 行：scroll [1080,468] ×2 |
| exit_confirm_quit | live_exit_confirm.png（1600x900，退出确认弹窗） | QUIT → NEXT（f1 零动作，不重复点开）；f2 点专用退出锚点 exit_confirm_btn @740,520（绝不用 cancel/close 泛化锚点）→ PREPARE 回房 | 2 行：none（NEXT）；left_click [740,520]（QuitGame-confirm，PREPARE） |
| disconnect_modal_missing | —（素材缺失） | BLOCKED | 无 ledger 行（如实缺） |

## 4. 运行结果（验证于 db73fd9）

```bat
.venv\Scripts\python.exe tools\run_frozen_replay.py --check
```
```
fail_panel_preempt           | off | PASS | frames=3
giveup_panel_not_fail        | off | PASS | frames=2
archive_challenge_open       | off | PASS | frames=1
main_hud_idle                | off | PASS | frames=2
stage_select_scroll          | off | PASS | frames=2
exit_confirm_quit            | off | PASS | frames=2
disconnect_modal_missing     | off | BLOCKED（真实断线素材缺失，G2）
Summary: Total=7 Passed=6 Blocked=1 Failed=0        （exit 0）
```

```bat
.venv\Scripts\python.exe tools\run_frozen_replay.py --diff --out docs\baselines\R0_LEDGER_20260811
```
```
[off]   ledger rows=12 -> docs\baselines\R0_LEDGER_20260811\off.jsonl
[shadow] ledger rows=12 -> docs\baselines\R0_LEDGER_20260811\shadow.jsonl
off/shadow ledger compare: off=12 rows, shadow=12 rows, diffs=0
[OK] 冻结回放全部场景 PASS，off/shadow ledger diff=0
```
ledger 行字段与 compare_ledger 等价规则对齐（fixture_id/phase/context/action_name/action_kind/
click_point/required；hwnd/score/status 易变字段忽略）。

## 5. 验收表

| 验收项 | 结果 | 证据 |
|---|---|---|
| 六类场景可运行、断言通过 | PASS（6/6） | §4 输出 |
| off/shadow ledger diff 场景 ≥2 | PASS（6 场景全跑，12 行 diff=0） | `docs/baselines/R0_LEDGER_20260811/{off,shadow}.jsonl` |
| 断线场景如实标注素材缺失 | PASS（BLOCKED，未伪造） | manifest.json disconnect_modal_missing.material_gap |
| 不碰生产；不产生输入 | PASS（dry_run=True + FakeInputExecutor；未修改 src/） | 运行日志 ledger 全部 dry_run |
| 960×540 不涉及 | PASS（范围外，NOT_APPLICABLE 口径） | 本集无 960×540 素材 |

## 6. 过程中发现的问题（如实记录）

1. **面板 WAIT_MUTATION 像素路径潜在崩溃**（生产代码，不在本次修改范围）：`_panel_mutation_confirmed`
   把 BGR 3 通道 ROI 传给 `_hero_changed_pixels` → `cv2.countNonZero(3 通道)` 在 OpenCV 4.14/5.0
   均抛 `cn == 1` 断言失败。触发条件：面板点击后**同帧/面板仍可见**的下一 tick（刷新按钮场景）。
   现有单测通过 patch `_panel_mutation_confirmed` 规避，从未覆盖真实像素路径。冻结回放集刻意
   避开该路径（giveUp 场景第二帧用面板已关闭帧），**并作为已知缺陷上报**（候选修复：
   `_hero_changed_pixels` 先 `cvtColor` 转灰度，属生产修改，冻结期内不做）。
2. fail_panel.jpg（N0 同名基准）当前 fail/gameFail 模板均不命中（giveUp 0.928 + 技能刷新锚点），
   因此 fail+panel 场景改用 idx_a 帧 002238/002694（fail 模板真实命中）；该差异已在 case.json
   description 中注明，N0 基准口径不受影响。
3. rec9/rec10（idx_a/idx_b）为 1920×1080 全桌面捕获（1600×900 游戏窗在内），故 fail/giveUp 场景
   帧分辨率如实标注为 1920×1080 full-desktop；HUD/stage/存档/退出场景为纯窗口捕获（1600×900 族）。

## 7. 命令

```bat
:: 全部场景（off）
.venv\Scripts\python.exe tools\run_frozen_replay.py
:: 单场景
.venv\Scripts\python.exe tools\run_frozen_replay.py --only giveup_panel_not_fail
:: off/shadow 双跑 + ledger diff（门禁：diff 必须 0）
.venv\Scripts\python.exe tools\run_frozen_replay.py --diff --out docs\baselines\R0_LEDGER_20260811
:: 门禁退出码（0=全部必需可跑 PASS 且 diff=0；BLOCKED 不判失败）
.venv\Scripts\python.exe tools\run_frozen_replay.py --check
```

## 8. 风险与后续

- 断线场景保持 BLOCKED（G2），实机采集（tools/net_block.py + 命名保存）后按 F8 补场景；
- 本集契约冻结于 db73fd9；后续任何生产改动（尤其 S0/面板 FSM/退出链）后必须重跑本集验证；
- 素材均引用既有 fixtures；若上游 fixture 被替换，case.json 的 file 路径同步校验（loader 启动即报错）。
