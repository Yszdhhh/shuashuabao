# R0 回放回归集盘点（R0.1）

> 日期：2026-08-11　分支：`codex/ocr-hybrid`　HEAD：265bd76（O3 状态修正提交）
> 依据：docs/NEXT_STAGE_EXECUTION_BLUEPRINT_20260811.md §15 R0.1 清单逐项盘点；
> 覆盖口径 = fixtures/manifest.json（P0-B 回放）、fixtures/scenarios/*/case.json（场景回放）、
> tests/test_*（单元/回归）、tests/performance/fixtures（N0 十二类基准）、fixtures/ocr_choices（OCR 数据）。
> 本文件只盘点与登记缺口，不新增 fixture（新增清单见 §5，实机采集后执行）。

## 1. R0.1 清单逐项盘点

| # | R0.1 要求 | 已有覆盖（文件/测试名，证据） | 缺口 | 状态 |
|---|---|---|---|---|
| 1 | fail+panel 独立场景 | ① N0 基准 fixture：`tests/performance/fixtures/fail_panel.jpg`（来源 rec_fine_bug/bug_00007.jpg，秘境局 t=2083s，失败+面板+光标 bug 证据窗；N0_BENCHMARK fail_panel warm_changed P50=6597ms，context_verified=MAIN_LINE）② `tests/test_s0_safety_state_machine.py::test_strong_fail_with_panel_preempts_selection`（合成 matcher 证据）③ `fixtures/scenarios/fail_recovery_three_frames/case.json`（fail→ok→close 三帧恢复，**XFAIL**：缺当前版全屏失败/断线弹窗证据，复用 skill_choice_3.png 作三帧）④ D0_SESSION_MAP §5：a 001471-001474 fail(fail) 真实失败候选；fail+面板并存区段已登记 | fixtures/manifest.json 无 fail 页 replay 条目（P0-B 回放清单无 FAIL page fixture）；scenario 为 XFAIL（真实弹窗素材缺失）；960×540 无 | 部分覆盖 |
| 2 | giveUp+panel 独立场景 | ① N0 基准 fixture：`tests/performance/fixtures/giveup_panel.jpg`（idx_b/000105.jpg，三普通局 t=104s，giveUp 模板命中面板「放弃」按钮 0.88 误检教训窗）② `tests/test_s0_safety_state_machine.py::test_giveup_only_panel_is_not_failure` ③ `tests/test_p1a1_main_line_controls.py::test_choice_panel_giveup_not_treated_as_fail` ④ D0_SESSION_MAP §5 大量 giveUp 命中帧（a/b 共 80+ 帧段，全部有面板锚点，按 S0 语义不判失败）⑤ `fixtures/ocr_choices/sources.json` has_giveup=true 条目 | manifest 无 giveUp+panel replay 条目；无独立 scenario case；960×540 无 | 部分覆盖 |
| 3 | 存档挑战独立场景 | ① `fixtures/manifest.json::post_game_archive_panel`（fixtures/replay/archive_challenge_panel.png → ARCHIVE_CHALLENGE_PANEL，expected_action none，required）② `tests/test_p1b0_post_game.py::test_archive_panel_anchor` ③ `tests/test_p1a2_challenge_controls.py::test_regressions_post_game_archive_boss_longzhu_priority` ④ `fixtures/ocr_choices/frames/live_postgame_20260808/live_archive_{challenges,panel,start_panel}.png` ⑤ D0_SESSION_MAP §5 postgame ARCHIVE_PANEL（a 000856-000863、b 000706-000715 等） | 无 scenario case（只有静态 manifest 条目 + 单测）；960×540 无 | 覆盖 |
| 4 | 主线 HUD 独立场景 | ① `fixtures/manifest.json`：main_line_auto_off / main_line_auto_on / challenge_coin_off / challenge_wood_off / challenge_experience_off / challenge_treasure_off（6 条，fixtures/replay/main_line_auto_*.png）② `tests/test_p1a1_main_line_controls.py`（18 个测试：auto task on/off、retry、输入种类、技能选择等）③ `tests/test_p1a2_challenge_controls.py`（15 个测试）④ N0 基准 idle_hud（main_line_auto_on.png 来源）⑤ `fixtures/ocr_choices/frames/rec*_ingame` | 960×540 HUD 帧无（当前全部 1600×900/1920×1080） | 覆盖（1600×900） |
| 5 | stage 独立场景 | ① `fixtures/manifest.json`：stage_select_1936x1066（expected_action SelectStage-target）+ neg_stage_not_found + neg_stage_ambiguous ② `fixtures/live_postgame_20260808/live_stage_select.png`（1600×900）③ `tests/test_stage_selector.py`（11 个测试）④ `tests/test_ui_scale.py::test_stage_select_recognized_at_960x540`（**cv2.resize 合成** 960×540）+ `test_baseline_1600x900_still_recognized` + B站 852×480 真实压缩帧（ticket 非 0）⑤ `fixtures/scenarios/`：stage_starting_env_hud、start_challenge_flow（PASS）、ticket_zero_archaeology（**XFAIL**：无 0/120 券真实三帧） | 960×540 真实窗口选关页帧无（合成缩放 + 852×480 B站帧，非 960×540 实机采集） | 覆盖（1600×900） |
| 6 | 退出确认独立场景 | ① `fixtures/live_postgame_20260808/live_exit_confirm.png`（1600×900）② `fixtures/manifest.json`：quit_game_1616x939（QuitGame）+ neg_quit ③ `tests/test_external_review_regressions.py::test_exit_confirm_fixture_never_selects_cancel` ④ `tests/test_temporal_same_room_loop.py`（live_exit_confirm 帧上验证每 tick ≤1 输入）⑤ `tests/test_s0_safety_state_machine.py`（退出确认 → NEXT → PREPARE 回房，_find_exit_confirm 打桩）⑥ `tests/test_p0c1_fixes.py::test_quit_next_use_only_dedicated_anchors` | 无 scenario case（只有静态 manifest 条目 + 单测）；960×540 无 | 覆盖（1600×900） |
| 7 | 960×540 窗口覆盖 | ① `tests/test_ui_scale.py`：960×540 = 1600×900×0.6 缩放合成帧（`cv2.resize(live_stage_select, (960,540))`，非真实采集）② B2 评测负样本 `neg_live_e2e_20260807_20_t9_1968096`（960×540 加载画面，负样本）③ B站 852×480 压缩帧（选关页） | **真实 960×540 正面板 = 0**（O3/D0 BLOCKED：技能/羁绊/宝物每类 ≥10 缺；禁止缩放伪造，需用户实机采集） | **BLOCKED** |
| 8 | 1600×900 窗口覆盖 | 主素材分辨率：manifest 全部 fixture、live_postgame_20260808 全套、tests/performance fixtures 11 类、ocr_choices 正负样本均 1600×900/1616×939/1586×892；B2 评测素材表按 1600×900 逐条 PASS | 无显著缺口 | 覆盖 |
| 9 | off/shadow 组合 ledger diff | ① `tools/ocr_sidecar_ledger_check.py`：off/shadow 双模式全 manifest replay + compare_ledger 等价校验（fixture_id/phase/context/action_name/action_kind/click_point/required 七字段）② `tools/compare_ledger.py`（等价规则实现）③ O4_SHADOW_20260811.md §7：off=32 rows / shadow=32 rows / diffs=0（证据 docs/baselines/O4_LEDGER_20260811/{off,shadow}.jsonl）④ `tests/test_ocr_shadow.py`（9 个 sidecar 协议测试） | ocr_mode 尚未被 mediator 消费（接线波未到）：当前 shadow 零输入权已证；fixture 扩展后需随回归集重跑；960×540 fixture 加入后需补同矩阵 | 覆盖（现行 32 fixture 矩阵） |

## 2. 汇总：缺口清单（与 O3 BLOCKED 一致性标注）

| 缺口 | 缺失内容 | 所需素材 | 阻塞状态 |
|---|---|---|---|
| G1 真实 960×540 正面板 | 每类（技能/羁绊/宝物）≥10 张真实 960×540 面板帧；当前 0（合成缩放与 852×480 不计数） | 游戏窗口 960×540 实机录制/panel_sample 自动收集 → 每类 ≥10 episode 主样本（`tools/collect_machine_material.py` 步骤 A/C） | **BLOCKED**（与 O3 `真实 960×540 正样本 ≥10/类`、D0 门禁 3 一致） |
| G2 真实断线弹窗 | gameDisconnect/retryConnect 命名帧 ≥1；6333 帧（idx_a 2778 + idx_b 2569 + legacy 986）扫描 0 命中；fail_recovery_three_frames XFAIL 与 manifest missing_disconnect_modal 均由此产生 | 断网/关服务端/`tools/net_block.py` 阻断触发 → 全屏弹窗帧命名保存（步骤 B） | **BLOCKED**（与 O3 `真实断线弹窗素材`、S0_STATUS missing_disconnect_modal 一致） |
| G3 fail/giveUp replay 条目 | fixtures/manifest.json 无 FAIL 页 / giveUp+panel 条目（当前只有 N0 基准与单测/场景 XFAIL） | 从已有素材落条目：fail_panel.jpg（rec_fine_bug）、giveup_panel.jpg（idx_b 000105）→ 正式 fixture 帧 + manifest 条目 + scenario case | 素材已有，接线待做 |
| G4 退出确认 / 存档挑战 scenario case | 无独立场景回放 case（只有静态 manifest 条目 + 单测） | 用现有 live_exit_confirm.png / archive_challenge_panel.png 编写 case.json | 素材已有，接线待做 |
| G5 960×540 断线/退出/存档/主线 HUD 帧 | 各场景 960×540 版本 | 960×540 实机采集（随 G1 一并完成） | **BLOCKED** |

## 3. 建议新增 fixture 清单（R0.1 回归集增量）

| 序号 | 新增项 | 类型 | 来源素材 | 验收 |
|---|---|---|---|---|
| F1 | `fixtures/replay/fail_panel.png`（1600×900 全屏，fail+面板并存）+ manifest 条目（page=FAIL 或 MAIN_LINE+fail 抢占，expected_action 按 S0.1） | P0-B manifest | rec_fine_bug/bug_00007.jpg（N0 已用） | replay status=PASS；fail 抢占面板语义断言 |
| F2 | `fixtures/replay/giveup_panel.png`（giveUp 按钮 + 面板锚点）+ manifest 条目（expected_action none，负语义） | P0-B manifest | idx_b/000105.jpg（N0 已用） | replay PASS；断言不判失败、0 输入 |
| F3 | scenario `fail_recovery_three_frames` 真实化：三帧替换为真实 fail 弹窗帧（fail→ok→close），移除 XFAIL | scenarios | 实机失败弹窗素材（G2 采集窗口顺带） | case 全绿，XFAIL_REASONS 移除 |
| F4 | scenario `giveup_panel_only_not_fail`（giveUp 单独出现+面板锚点 → 不判失败、无恢复点击） | scenarios | giveup_panel.jpg | case 全绿 |
| F5 | scenario `exit_confirm_quit_to_room`（退出确认 → 点退出 → 回房 PREPARE） | scenarios | live_exit_confirm.png + room_waiting_host.png | case 全绿 |
| F6 | scenario `archive_challenge_open`（存档挑战面板 → 各卡片动作策略） | scenarios | archive_challenge_panel.png + live_archive_*.png | case 全绿 |
| F7 | 960×540 真实帧组：每类 ≥10 面板 + stage + 退出确认 + 主线 HUD + fail/giveUp（如需） | manifest/ocr_choices | `tools/collect_machine_material.py` 采集 | 分辨率恰为 960×540；O3 门禁解除 |
| F8 | 断线弹窗帧组：`gameDisconnect_*.png` / `retryConnect_*.png` ≥1 → fixtures/replay/disconnect_modal.png + manifest 条目（替换 missing_disconnect_modal） | manifest/ocr_choices | `tools/net_block.py` + 步骤 B 采集 | manifest missing 项转真；S0 断线路径真实素材验证 |
| F9 | off/shadow ledger 矩阵扩展：新增 fixture 后重跑 `tools/ocr_sidecar_ledger_check.py`，输出 off/shadow 两 JSONL 与 diff=0 | 工具运行 | F1-F8 落地后 | compare_ledger diffs=0 |

## 4. 执行顺序建议

1. 现有素材立即可做：F1、F2、F5、F6（G3/G4 接线，无新素材依赖）；
2. 用户实机采集（`tools/collect_machine_material.py` 指引）后：F3、F7、F8（解除两条 O3 BLOCKED）；
3. 全部 fixture 落地后：F9 重跑 off/shadow ledger diff，作为 R0.1 回放门禁收口。

## 5. 结论

- **BLOCKED（960×540 与真实断线弹窗）**：与 O3 门禁两条 BLOCKED 完全一致，需用户实机素材；
- **可离线推进**：F1/F2/F5/F6 用仓库既有素材即可补齐（fail/giveUp replay 条目、退出确认/存档挑战 scenario case）；
- 1600×900 覆盖充分；off/shadow ledger diff 工具与 32×0 基线已就位，fixture 扩展后重跑即可。
