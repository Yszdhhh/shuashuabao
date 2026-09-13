# 刷刷宝外部审查包（2026-09-13）

审查基准：主仓库 `main` @ `b4cf93f`（PR #19 的 merge commit）；订阅服务端 `feat/account-layer-20260913` @ `cdf9603`。

- **审查提示词**：[REVIEW_PROMPT.md](REVIEW_PROMPT.md)。把全文交给审查 agent。
- **正式版进度评估**：[RELEASE_PROGRESS_ASSESSMENT_20260913.md](RELEASE_PROGRESS_ASSESSMENT_20260913.md)
- **账号层设计**：[ACCOUNT_LAYER_DESIGN_20260913.md](ACCOUNT_LAYER_DESIGN_20260913.md)

## 链接

| 用途 | 链接 |
|---|---|
| PR #19（收敛合并，已合入） | https://github.com/Yszdhhh/shuashuabao/pull/19 |
| PR #20（看板摘要转义，CI 中） | https://github.com/Yszdhhh/shuashuabao/pull/20 |
| 本次业务改动 diff（f0243f5 → b4cf93f） | https://github.com/Yszdhhh/shuashuabao/compare/f0243f5...b4cf93f6a2c716aa44f29abf1cd54caacaea09fa |
| main 代码快照 | https://github.com/Yszdhhh/shuashuabao/tree/b4cf93f6a2c716aa44f29abf1cd54caacaea09fa |
| PR head 的 CI（绿） | https://github.com/Yszdhhh/shuashuabao/actions/runs/34744566530 |
| 订阅服务端分支 | https://github.com/Yszdhhh/shuashuabao-subscription-lab/tree/feat/account-layer-20260913 |

## 建议阅读顺序

1. **先看全局**：
   - `AGENTS.md`：仓库纪律（门禁、红线）
   - `docs/handoff_20260912/CONVERGENCE_REPORT_20260912.md`：09-12 版本收敛，两条线合一
   - 本包的 `RELEASE_PROGRESS_ASSESSMENT_20260913.md`
2. **A. PR 合并与收敛**：
   - PR #19 的描述（含 `-s ours` 的依据和校验）
   - `docs/handoff_20260912/EXECUTOR_PROMPT_KANBAN_HITCH_SETTINGS.md` 第 4 节：实机身份规则
   - `tools/live_harness_identity.py`、`tools/live_scenario_capture.py`（`_scenario_identity`）
3. **B. 架构**：
   - `docs/ARCHITECTURE.md`、`docs/ARCHITECTURE_CONVERGENCE_20260904.md`
   - `docs/architecture/LOCAL_ARCHITECTURE_REALITY_AUDIT_20260910.md`、`docs/architecture/RUNTIME_ARTIFACT_IDENTITY_20260910.md`
   - 代码：`desktop_app.py`、`src/shuabao/shell/web_config_shell.py`、`src/shuabao/shell/dashboard_facade.py`、`ui-v2/src/main.ts`、`ui-v2/src/bridge/*`、`config/mode_specs.json`
   - 工具：`tools/release_gate.py`、`.github/workflows/ci.yml`、`docs/baselines/GATE_BASELINE.json`
4. **C. 业务板块**：
   - `docs/reviews/HITCH_LIVENESS_AUDIT_20260912.md`：蹭车无进展监督
   - `docs/LOCAL_AGENT_HANDOFF_20260912_HITCH_REVIEW.md`：蹭车实机问题与修复
   - 代码：`src/shuabao/policy/boss_order.py`，以及 `src/shuabao/mediator.py` 中的 `_maybe_challenge_configured_boss`、`_handle_boss_anomaly_retry_or_skip`、宝物 V 门禁（搜 `_hitch_last_treasure_unconfirmed_fp`）、`_hitch_liveness_supervise`
   - 测试：`tests/unit/test_boss_order_policy.py`、`tests/test_boss_order_integration.py`、`tests/test_hitch_treasure_v_gate_20260913.py`、`tests/test_p1b0_post_game.py`
   - 配置：`config/challenge_boss_catalog.json`
5. **D. 订阅与发布**：
   - `docs/SIGNED_ENTITLEMENT_PROTOCOL.md`、`docs/CURRENT_STATUS_AND_HANDOFF_20260903_SUBSCRIPTION_TLS.md`、`docs/CLOUD_SUBSCRIPTION_AUDIT_PACKAGE_20260903.md`、`docs/RELEASE_P0_INSTALL_AUDIT_20260904.md`
   - 代码：`src/shuabao/subscription_client.py`、`src/shuabao/subscription_permit.py`、`build_release.ps1`
   - 服务端仓库：`docs/ARCHITECTURE.md`、`docs/SECURITY_BOUNDARY.md`、`docs/KNOWN_GAPS.md`、`docs/RUNBOOK.md`、`bridge/app/main.py`、`bridge/app/services/event_processor.py`、`bridge/app/services/permit_issuer.py`
   - 本包的 `ACCOUNT_LAYER_DESIGN_20260913.md`

## 报告放哪里

审查报告写到本目录的 `EXTERNAL_REVIEW_REPORT.md`，推送到本分支（`review/package-20260913`），不开 PR。
