# 云端审查交接提示词（Codex / GPT-5.6 Sol High）

> 目标模式任务书。执行方：codex（官方订阅，模型 gpt-5.6-sol, reasoning=high）。
> 唯一工作目录：`G:\刷刷宝\GameScript-Local`（分支 `trial-merge`）。**禁止**在
> `G:\刷刷宝\Worktrees\*` 或 `C:\Users\10639\.codex\worktrees\*` 下改代码——那是
> "OMP 执行不落地" 的头号根因（见下文）。

---

## 1. 任务目标（按序执行，全部要留证据）

1. **架构梳理**：通读 `src/shuabao/mediator.py` 战后状态机（`_post_game_state` /
   `_tick_main_line` 战后分支 / `_advance_recovery`）与 `shell/dashboard_facade.py`，
   输出一页架构图（状态 + 转移 + 门禁），落盘 `docs/ARCHIVE_POSTGAME_REVIEW_20260901.md`。
2. **问题排查（两处保留的 P1）**：上会话审查者（GLM-5.3）标记为 FAIL 的两项按设计保留，
   需要你用实机帧/fixtures 做深度复核并给出结论（改 or 加固 or 维持）：
   - P1-a `mediator.py:~8596-8610`：`archive_active/heirloom_active` + 通用
     `_is_in_game_hud` 即清 `_post_game_pending`。审查者担心入口点击失败/加载过渡帧
     误触发。反证：真实失败方向是提前结束一局（安全侧），且有
     `test_enabled_secret_realm_uses_npc_then_yes_and_verifies_hud` 实帧背书。
     请评估加"连续 2 帧 HUD"或目的地专属锚点的代价与回归风险。
   - P1-b `mediator.py:~4497-4509`：ARCHIVE_PANEL 分类允许 `_post_game_pending`
     替代专属锚点（实机修复：部分卡片未即时变绿+标题 miss 时必须能分类）。
     审查者担心过渡弹窗右上角 X（专属模板 archive_panel_close @0.80，ROI
     0.55-0.70/0.15-0.35）撞车 → 4x2 固定卡位点击。请用
     `fixtures/` 现有实帧扫描全部非存档弹窗验证是否存在撞车，有则加
     "pending-only 分类需连续 2 tick 稳定"去抖。
3. **基建稳定**：跑通 `python tools/release_gate.py`（4/4）+ 全量 pytest；
   若发现 flaky 测试，单独列出（不要顺手大改）。
4. **打包落地**：确认 `build_identity.json` 的 `source_sha == git rev-parse HEAD`
   且 `source_tree_clean == true`；桌面 `刷刷宝.lnk` 指向 `Desktop\ShuaBao\ShuaBao.exe`。
   若 HEAD 已前进而 EXE 未重建，跑 `powershell -File build_release.ps1`（会重跑门禁）。
5. **完成后**：提交 + push 到 `origin/trial-merge`，commit message 前缀
   `review(codex-sol):`。

## 2. 背景：今晚已完成的整合（全部已验证）

- 合并 `codex/live-test-handoff-20260831`（bbd5490+）→ trial-merge：
  存档 8 卡 → 时光之穴滚动选末位 Boss → 传家宝链 → 大秘境右键确认（HUD 验证）。
- 实机复盘修复：失败页红退出按钮在绿按钮被鼠标遮挡时仍可点击
  （`_find_failure_exit_button` 红/绿兄弟 + 左下半区红兜底 + gameFail 下沿按钮带约束）；
  未验证 archive 守卫只对"无战后上下文"帧 Fail-Closed，`_post_game_pending=True`
  过渡帧豁免（p0c1/p1a1/p1a2 三套测试已对齐新契约）。
- 看板整合：`config/mode_specs.json` normal_farm 可见设置加入
  `cjb_boss/sgzx_boss/auto_secret_realm`；原生窗与 WebShell 均已具备三链路配置项；
  订阅激活（license gate）已接入 facade/原生窗/桌面入口。
- 审查修复（4bb58e2）：route 随新局重置、env key 优先级、先落盘后写 env、
  红兜底按钮带约束。
- 验证状态：pytest 1115 passed / 1 skipped / 2 xfailed；release_gate 4/4 PASS
  （frozen_replay 中 disconnect_modal_missing=BLOCKED 为基线已知项）。

## 3. 前期问题清单（omp 执行不落地根因，详见 docs/OMP_LANDING_GAP_20260901.md）

1. **多 worktree 分裂**：7 个 worktree 并存，OMP 会话曾在 C:\tmp、Desktop 副本、
   旧 Integration worktree 启动——改 A 副本、桌面入口用 B 副本。
2. **桌面 EXE 由 build_release.ps1 手动重建**：不跑构建，桌面 EXE 永远停在
   source_sha=05ed271 的旧版（本夜已重建部署到新 HEAD）。
3. **改完即宣称完成**：无 build_identity 校验、无启动证据。本次起强制三位一体：
   改动清单 + 校验命令输出 + 运行态证据。
4. **审查在错误 cwd 跑**：pytest 在 worktree 绿 ≠ 主树绿；主树曾有 22 个未提交文件。

## 4. 现在稳定可用的链路（验收清单）

| 链路 | 状态 | 证据 |
| --- | --- | --- |
| 存档挑战 8 卡 → 时光之穴末位 Boss → 关面板回广场 | 实机验证 | live READY + 45 用例（p1b0） |
| 传家宝挑战链（OpenHeirloomChallenges → 已挑战确认） | 实机验证 | test_heirloom_* |
| 大秘境（右键 OpenGreatRift → ConfirmGreatRift → HUD） | 实机验证 | test_enabled_secret_realm_* |
| 失败页退出（红按钮直点 / 左上退出 + 标准确认框） | 实机验证 + 今晚加固 | test_live_run_205044_regressions |
| 战后链看板配置（cjb_boss / sggx_boss / auto_secret_realm） | 已整合 | mode_specs + facade 测试 |
| 订阅 license gate（启动前校验） | 已整合 | test_dashboard_facade_runner |

## 5. 验收标准（用户明早起验收）

- codex 审查报告落盘且结论明确；
- `python -m pytest` 全绿 + gate 4/4；
- `build_identity.json.source_sha == HEAD`；
- push 完成，`origin/trial-merge` 最新提交可见；
- 未完成项明确列出，回交主会话继续。
