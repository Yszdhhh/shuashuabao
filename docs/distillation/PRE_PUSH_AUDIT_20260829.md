# Pre-Push Audit — Stage 2A/B0 收口

日期：2026-08-29
仓库：`G:/刷刷宝/GameScript-Local`
分支：`trial-merge`
HEAD：`ffb3cfd`

## 审计结论

| 项目 | 结论 |
|---|---|
| Stage 2A/B0 的 curated release gate | `PASS`（4/4） |
| Panel timeout→cooldown→reopen 宏观活锁 | `PASS`：episode 级 fail-closed 收口；同一异常面板不能跨 episode 无限 reopen |
| Panel episode budget 语义 | `PASS`：只计异常 episode；正常 skill/bond/treasure 成功 episode 不消耗预算，三类 counter 独立，进入新 round 全清零 |
| 长线程 P0 的“面板级”liveness | `PASS`：有可复现 harness 和状态不变量 |
| Panel P0 是否完全 CLOSED | `NO`：机制级已 CLOSED，但真实长线程证据与 round fail-closed stall 风险尚未完全关闭 |
| 长线程端到端实机 liveness | `NOT FULLY PROVEN`：现有长测是观测 telemetry，不是修复后硬件闭环证明 |
| treasure description 删除建议 | `ALLOW_PROPOSAL_ONLY`：decision-equivalence 通过，但运行时调用仍保留 |
| `main_hud_idle` frozen replay | `PASS`：OpenSkillPanel→OpenBondPanel 是已确认的 bond-first 真实修复 |
| `giveup_panel_not_fail` | `PASS`：真实三帧 replay；baseline 可更新 |
| `disconnect_modal_missing` | `BLOCKED`：保持不变 |
| 全量 `pytest tests` | `HOLD`：当前冻结 30 个既存失败 nodeid，不能写成全仓全绿；未过滤 Windows 运行还会在 desktop Qt 测试中发生进程级 access violation |
| Push / merge | `NO`：本次没有执行 |

因此，Stage 2A/B0 已达到本仓库 curated release gate 的收口条件，但 Pre-Push Audit 的总状态仍是 `HOLD`：全量 pytest 尚未绿，当前有 30 个精确 baseline nodeid，且 disconnect 仍缺实机素材。这里的 `PASS` 只表示已验证的机制/证据边界，不扩大为完整硬件长跑保证。

## 运行证据

以下命令均在项目 `.venv` 中执行：

| 检查 | 结果 |
|---|---|
| `python -m pytest tests/test_panel_liveness_harness.py tests/test_stage2b0_evidence_tools.py tests/test_live_run_205044_regressions.py tests/test_l1_cycle_recheck_merchant.py tests/test_mediator_choice_four_slot_integration.py tests/test_ocr_shadow.py tests/contract/test_choice_policy_wiring_contract.py -q` | `114 passed` |
| `python tools/release_gate.py --json` | exit `0`；pytest `328` passed；frozen replay `6 PASS + disconnect BLOCKED`；scene `132 ok / 0 missing`；asset `351/351`；contract `56`；gate `4/4 PASS` |
| repo-wide failure-set verification | 稳定隔离运行得到 `27 failed, 830 passed, 1 skipped, 2 xfailed, 188 subtests passed`；`test_desktop_app.py` 隔离出另外 3 个失败，其余 94 个 desktop tests 通过；其他 Qt 模块均通过 |
| 未过滤 `python -m pytest tests -q` | 复现同一 Atlas 失败后，在 Windows desktop Qt setUp 触发 access violation，pytest 无法打印完整汇总；该进程级 runner caveat 不伪造为额外 nodeid |
| `python tools/replay_treasure_desc_equivalence.py --json-out docs/distillation/TREASURE_OCR_DECISION_REPLAY.json` | `compared_rows=4095`，`mismatch_count=0`；enabled/disabled 的 SELECT/CLOSE/REFRESH/slot 决策一致 |
| `python -m pytest tests/test_vision_corpus_coverage.py -q` | `3 passed` |
| `git diff --check` | 无内容错误；仅有 Windows 工作区的 LF→CRLF 提示 |

全量 pytest 的失败属于本次 Stage 2A/B0 curated gate 未覆盖的既存范围：精确集合共 30 项（Atlas 7、pause-overlay 1、policy/history 1、L0 detector/create-room 6、L1 choice fixture 7、scenario replay 1、skill metadata/ticket/trace/ui-scale 4、desktop UI 3）。它们没有被 Coverage 阶段顺手修复，也没有据此修改生产策略或伪造 baseline。完整 nodeid 以 [REPO_PYTEST_NO_NEW_FAILURES_20260829.json](../baselines/REPO_PYTEST_NO_NEW_FAILURES_20260829.json) 为准。

## P0 liveness 收口证据

`Panel timeout→cooldown→reopen` 已通过最小 harness 覆盖三件事：

1. proactive open timeout 计入现有 `_panel_episode_count`，不再把这类 timeout 当作 episode 外事件。
2. 达到同一 kind/round 上限后，现有 panel 状态转为永久 `COOLDOWN`（`cooldown_until=inf`），后续 episode 不再 reopen。
3. 仍遮挡 UI 的异常面板不会被当作“已经推进”；anchor/遮挡仍然是阻塞条件，避免用忽略面板伪造 liveness。

4. budget 只记录异常：主动打开可见超时、panel episode hard-deadline、CLOSING 无法找到关闭锚点才增加对应 kind 的 counter；正常成功打开/选卡/关闭的 episode 不增加。
5. `skill`、`bond`、`treasure` 使用同一个字典的三个独立 key；进入新 `STAGE_SELECT` 会清空 counter、cooldown 和 panel state。

该修复复用了现有 `panel episode / cooldown / count` 状态，没有新增 watchdog、线程、recovery manager、fallback 或 FSM。它证明的是宏观活锁不变量；现有长测的 2,996.4 秒 / 6,525 ticks 只作为历史 session telemetry，不能替代修复后实机长跑。

### 理论 worst-case stall

按当前默认参数：`panel_episode_limit_per_kind=24`、`panel_hard_deadline_s=15s`、`panel_visible_timeout_s=2s`、异常路径 cooldown 使用 `ui_action_interval_s=1.5s`。

- 如果异常 panel 已可见但永远没有有效进展，从“首次 hard-deadline 失败”到该 kind 进入永久 `COOLDOWN` 的预算上界约为：`(24-1) × (15+1.5) + 1.5 = 381s`，约 6 分 21 秒。
- 如果是主动打开后始终不可见，约为：`(24-1) × (2+1.5) + 1.5 = 82s`。
- 达到永久 `COOLDOWN` 后，仍遮挡 UI 的 panel 会继续由 FSM 持有，不能继续 reopen，也不会假装推进；因此从首次异常到真正的 round hard-deadline fail-closed，默认 `round_timeout_s=3600s` 时最坏仍接近该局剩余的一小时（若首次异常在 round 起点，约 3600s）。

这是明显的长线程 stall 风险，本轮只记录，不新增 watchdog/recovery/fallback，也不调大结构或伪造进度。`Panel P0` 因此只在“异常重开不再无限重复”的机制层 CLOSED，整体仍标记 `NOT FULLY CLOSED`。

## OCR decision-equivalence 审计

- incident OCR shadow 中精确的 legacy treasure description selector 为 `12,276` 次，全部 `unavailable`。
- paired replay 只把 `SlotCandidate.description` 置空，SELECT/CLOSE/REFRESH/slot 决策完全一致，`mismatch_count=0`。
- 因此只能把“关闭无效运行时调用”标为 `ALLOW_PROPOSAL_ONLY`；当前没有删除调用，`description`、`negative_patterns`、`negative_names` 等业务语义仍保留。

详见 [TREASURE_OCR_DECISION_REPLAY.json](TREASURE_OCR_DECISION_REPLAY.json) 与 [TREASURE_OCR_AUDIT.json](TREASURE_OCR_AUDIT.json)。

## Frozen replay / baseline 审计

- `main_hud_idle` 当前期望为 `OpenBondPanel @ (1390,808)`；这是 bond-first 顺序修复的结果，不是随意改 baseline。
- `giveup_panel_not_fail` 使用真实三帧 replay 已通过，baseline 更新附有原因。
- `disconnect_modal_missing` 没有 current-version 实机 positive fixture，继续 `BLOCKED`；不使用合成帧替代。
- Gray_2x、cards template、HSV、`vision_profiles` 没有由本次 Coverage 接入生产。工作区已有的 Stage 2A/B0 运行时代码改动保持原边界；Coverage 新增的生成器只读素材/既有报告并输出 distillation 文档。

## Repo-wide pytest NO_NEW_FAILURES baseline

当前已把 30 个既有失败的精确 nodeid 固化在 [REPO_PYTEST_NO_NEW_FAILURES_20260829.json](../baselines/REPO_PYTEST_NO_NEW_FAILURES_20260829.json)。后续原则是：这些 nodeid 可以继续存在，但出现任何额外失败即视为 `NO_NEW_FAILURES` 违反；本 checkpoint 不修 Atlas、pause-overlay、历史 L0/L1 fixture、desktop UI 或 disconnect 历史问题。

## Git 拓扑与动作边界

审计采集时状态为：

```text
trial-merge...origin/trial-merge [ahead 7]
working tree: dirty（Stage 2A/B0 与本阶段 Coverage 产物均未提交）
push: not executed
merge: not executed
```

以上是 checkpoint 创建前的审计快照；随后只按下述边界建立本地 checkpoint，不 push、不 merge。Coverage 阶段只新增/更新 `tools/`、`tests/`、`docs/distillation/` 范围内的蒸馏/评测产物；生产接入状态为 `NOT_APPLIED`。

## Checkpoint 文件边界审计

本轮 checkpoint 只允许纳入以下类别：

- 生产代码：`src/shuabao/mediator.py`、`src/shuabao/settings.py`、`src/shuabao/vision/ocr_shadow/client.py`、`src/shuabao/vision/ocr_shadow/worker.py`。
- tests/tools：Stage 2A/B0 相关测试、`test_vision_corpus_coverage.py`，以及 OCR/card/eval/replay、asset manifest、release gate 工具；Coverage 生成器只使用标准库。
- fixture/baseline：`fixtures/baselines/replay_frozen/` 下的 manifest 与 `main_hud_idle` case，及 gate/pytest baseline JSON。
- docs/evidence：当前 [Pre-Push Audit](PRE_PUSH_AUDIT_20260829.md)、[Vision Corpus Coverage](VISION_CORPUS_COVERAGE.md)、对应 JSON/JSONL、OCR/card benchmark 和当前 status 文档。

明确排除在本 checkpoint 之外：

- 另一对话正在独立执行的 `tools/live_scenario_capture.py`、`tests/test_live_scenario_capture.py`；本轮不读写、不 stage。
- `config/vision_profiles.proposed.yaml`：冻结的 proposed 研发资产，不接生产。
- `tools/write_distillation_docs.py`：无业务语义的临时 scaffold。
- 旧的 Gemini/Stage 1 历史说明与过时审阅稿：保留在工作区供追溯，但不作为当前权威 checkpoint 证据。

对上述待提交路径做了文件级检查：没有图片扩展名、原始 corpus、incident 目录、录屏帧或 Gemini 临时文件；最大待提交文本文件是生产源码/benchmark JSON 级别，不存在大体积素材进入 staging 的路径。
