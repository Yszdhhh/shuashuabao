# ShuaBao Vision/OCR — Codex Stage 2A 审查结论

日期：2026-08-29  
范围：Gemini Stage 1 回传、当前 `trial-merge` 工作树、离线 OCR/模板证据、面板 FSM 安全性。

## 总结

Gemini 回传里有三类结论不能直接落生产：

1. **宝物 OCR 全量删除：REJECT。** 当前 trace 证明描述 OCR 可用性差，但没有选卡结果/业务结果标签，不能由低命中率推出“无业务价值”。保留名字/描述语义，读不到时继续 fail-closed。
2. **Gray_2x 直接替换六变体：NO_CHANGE。** 它明显更快，但在同一 155 条语料上整体 Top-1/Recall 略低，尚未达到生产候选标准。
3. **HSV/新视觉 profile/模板优先接线：本阶段不接。** `config/vision_profiles.proposed.yaml` 仍是 proposed，未改变 worker、mediator 或生产阈值。

本阶段只增加可重复的证据工具、资源泄漏门禁和测试；没有修改 `src/shuabao/` 生产识别或面板行为。工作树中原有的其他 dirty changes 保留不动。

## A. Git 拓扑

| 项目 | 结果 |
|---|---|
| 本地分支/HEAD | `trial-merge` / `ffb3cfdf55980801634b218a078635402f932fe2` |
| 远端 `origin/trial-merge` | `75135af1e56d800205b7fedf8f706328855eb28c` |
| 拓扑 | 远端提交是本地祖先；本地领先 7，远端独有 0 |
| 外部动作 | 未 merge、未 push、未 force-push、未清理工作树 |

## B. Refresh / Panel FSM

使用当前代码和 deterministic fake clock/input 做了分支审查；这些是 FSM 证据，不冒充实机修复证据。

| 场景 | 观察 | 结论 |
|---|---|---|
| refresh 命中且 `act_click=True` | 状态仍为 `ACTIVE`，`_skill_refresh_attempts=1`，动作暂存为 `refresh`，没有 mutation baseline | 刷新动作不等待卡片 mutation，但预算已计数；需继续依赖 refresh budget/episode fuse |
| `act_click=False` | attempts=0、无 pending action | 被拒点击不消耗预算，安全 |
| OCR 空、关闭锚点缺失 | 3 秒仍 `ACTIVE`/零输入；10 秒进入 `COOLDOWN` | 单 episode 有限端点 |
| refresh budget 耗尽 | 关闭动作进入 `WAIT_MUTATION`，不再继续刷新 | 预算分支存在 |
| 永久 OCR 空且策略 WAIT | 保持零输入，10 秒进入 `COOLDOWN` | 不会因空 OCR 盲点 |
| 自然面板持续重现 | episode 在约 10 秒后 cooldown；冷却后约 13/24/38 秒可再次开 episode | 单 episode 有界，但宏观上在 round deadline 前存在重复重开风险 |

风险来源是 `_maybe_open_choice_panel()` 在达到 `panel_episode_limit_per_kind` 后把该计数清零，而不是把该类型置为终止态；默认 round fuse 仍是更外层的 3600 秒。Stage 2A 只记录风险，不叠加新的 watchdog/recovery 行为。

## C. Gemini 语料证据链修复

`tools/build_vision_eval_manifest.py` 已把原始标注和实际文件事实分开：从 `corpus_root` 读取图片，重算真实 SHA-256、尺寸、64-bit dHash/pHash，并用算法生成 `phash_dhash_cluster_NNNN`。capture session 和近重复 cluster 均禁止跨 split。

当前清单：155 samples（skill 47 / bond 54 / treasure 54），7 capture sessions，`TRAIN_TUNE=44`、`BLIND_HOLDOUT=111`，151 clusters，其中 4 个 near-duplicate clusters / 8 samples，exact duplicate 为 0。原 Gemini 清单中 label-like cluster ID 和旧 hash 不再作为事实来源。

可复跑：

```powershell
python tools/build_vision_eval_manifest.py --generated-at 2026-08-29T00:00:00+00:00
```

输出：[VISION_EVAL_ANNOTATIONS.jsonl](VISION_EVAL_ANNOTATIONS.jsonl)、[VISION_EVAL_MANIFEST.jsonl](VISION_EVAL_MANIFEST.jsonl)。相同输入和时间戳重复生成的 SHA-256 一致。

## D. OCR 对照评测

命令：

```powershell
.\.venv-ocr\Scripts\python.exe tools/benchmark_vision_ocr.py --json-out docs/distillation/VISION_OCR_BENCHMARK.json
```

模型 hash gate 通过；硬件为 CPU / 4 threads。当前 worker 的六变体和 Gray_2x 使用同一清单、同一模型、同一运行机。

| 指标 | current_6_variant | gray_2x |
|---|---:|---:|
| overall Top-1 / Recall | 92.90% | 92.26% |
| overall Precision | 96.64% | 97.95% |
| overall FP / FN / unmatched | 5 / 11 / 6 | 3 / 12 / 9 |
| skill Recall | 97.87% | 97.87% |
| bond Top-1 | 83.33% | 81.48% |
| treasure Top-1 | 98.15% | 98.15% |
| single p50 / p95 | 122.50 / 172.51 ms | 20.63 / 26.62 ms |
| inferred panel sequential p50 / p95 | 368.69 / 457.91 ms | 62.61 / 74.41 ms |

结论：`candidate_decision=NO_CHANGE`。Gray_2x 的 skill recall 不差、延迟更好，但 overall Top-1 没有严格提升，不能进入 `PRODUCTION_CANDIDATE`，也没有接线。历史 O3 的 388 slots / 9 sessions 仍作为参考，当前 155 条清单标记 `NOT_COMPARABLE`，不替换历史结论。

## E. Cards 模板

当前 runtime inventory 是 39 个模板，和 `templates_index.json`/磁盘一致，不是 Gemini 文中 36 个。使用 3 槽、4 槽真实 panel frame，按槽位 title ROI 测试：

- threshold curve：0.50–0.95；operating threshold：0.82；
- approved positives：6；hard negatives：423；black-frame negatives：156；idle-HUD negatives：156；
- 0.82：positive 6/6、hard-negative false fire 0/423、black 0/156、idle 0/156；
- 0.90 时正例降为 5/6，说明不能只凭“越高越安全”抬阈值；
- 最高的 positive-slot 非目标模板相似分数约 0.517，仍低于 0.82。

报告：[CARD_TEMPLATE_BENCHMARK.json](CARD_TEMPLATE_BENCHMARK.json)。OCR bond 参考值（54 条 title crops，current Top-1 83.33%）单独标为 `REFERENCE_ONLY_NOT_COMPARABLE`，没有拿不同任务单位做虚假的优劣结论。模板也没有接入 production。

## F. Treasure OCR 贡献审计

报告：[TREASURE_OCR_AUDIT.json](TREASURE_OCR_AUDIT.json)。当前 trace 共 45,078 行，其中 treasure 24,645 行、4,118 个 name/description panel ID、单 panel 最多 12 次 OCR 调用：

- name：12,369 calls；750 `ok`、11,619 `unavailable`；raw non-empty 425、candidate non-empty 175；
- description：12,276 calls；全部 `unavailable`，其中 `inference_error=666`、`disabled=11,610`；raw/candidate non-empty 均为 0；
- 当前策略仍保有 7 个 negative names、14 个 negative patterns、6 个 must-take names，并开启 `refresh_on_no_safe`。

这证明 description OCR 目前没有可用输出，不证明它在业务上永远没有价值；缺少 selected action/outcome label，所以 full-removal 结论为 **REJECT**。下一步应先给 held-out trace 加安全/负面/must-take outcome 标签，再评估是否缩小 OCR 范围。

## G. Asset Leakage Gate

`ShuaBao.spec` 当前以 whole-tree 方式打包 `assets`。新增 [runtime_asset_manifest.json](../../config/runtime_asset_manifest.json) 显式记录每个路径的 purpose、provenance、reason、size 和 SHA-256；`tools/release_gate.py` 在现有 `scene_templates` 阶段执行：

- 351 个 runtime asset files；351/351 allowlisted；
- missing/stale/forbidden/metadata/hash mismatch 均为 0；
- 检查 whole-tree spec 声明；
- 只按路径 policy 和 allowlist 阻止 capture/failure/debug/evidence/training/corpus 等泄漏，不按 PNG/JPG 扩展名全局禁用；
- OCR sidecar 模型继续由 `models/ocr/MODEL_MANIFEST.json` 的 hash gate 管理，未改 production packaging 逻辑。

生成器：[generate_runtime_asset_manifest.py](../../tools/generate_runtime_asset_manifest.py)；门禁自检已通过。

## H. Tests

- Stage 2A 工具 + OCR shadow + 四槽 integration + choice-policy contract：36 passed；
- `tests/contract`：56 passed，111 subtests passed；
- release gate 的 pytest stage：328 passed；
- `tools/validate_scenes.py`：132 templates，missing=0；card bidirectional 120 checks pass。

完整 `python -m pytest tests -q` 当前仍有 7 个 `tests/test_atlas_view.py` failure（archive join、bond column、empty family、EX icon、奥术箭 lexicon projection、两处 apply diff）；这些不是本阶段新增工具造成的修改，仍需单独处理，不能宣称全套 pytest 全绿。

## I. 当前 release gate

当前完整 gate 是 **3/4 stages pass，exit=1**：

- pytest：PASS，328 passed；
- frozen replay：FAIL —— `main_hud_idle` 期望 `OpenSkillPanel`，实际 `OpenBondPanel`；`disconnect_modal_missing` 为 BLOCKED（缺真实断线弹窗素材）；
- scene/template + asset leakage：PASS；
- contract：PASS，56 passed。

`giveup_panel_not_fail` 实际已为 PASS，但旧 `GATE_BASELINE.json` 仍记录 FAIL，gate 正确提示“已修好，请更新快照”；本阶段没有擅自刷新基线，也没有把已有红项改成绿项。

## J. Blockers

1. `main_hud_idle` 需要先决定是更新夹具还是复核羁绊基础进度优先级；本阶段不改 L1 行为。
2. `disconnect_modal_missing` 必须用真实断线流程采集 `gameDisconnect/retryConnect`；不使用合成帧。
3. panel natural reappearance 的宏观重复风险需要真实长跑 trace 才能决定是否增加终止策略。
4. full pytest 的 7 个 atlas failures 需要独立 owner/证据链。

## K. Stage 2B 生产变更

当前没有进入 Stage 2B：Gray_2x 未达到候选条件，cards 只做证据评测，treasure OCR 未删除，proposed vision profile 未接线，也没有新增 HSV detector、retry/watchdog、model/fine-tune 或阈值变更。

## L. 证据文件

- [VISION_OCR_BENCHMARK.json](VISION_OCR_BENCHMARK.json)
- [CARD_TEMPLATE_BENCHMARK.json](CARD_TEMPLATE_BENCHMARK.json)
- [TREASURE_OCR_AUDIT.json](TREASURE_OCR_AUDIT.json)
- [VISION_EVAL_MANIFEST.jsonl](VISION_EVAL_MANIFEST.jsonl)
- [runtime_asset_manifest.json](../../config/runtime_asset_manifest.json)
- [release_gate.py](../../tools/release_gate.py)
- [test_stage2a_evidence_tools.py](../../tests/test_stage2a_evidence_tools.py)
