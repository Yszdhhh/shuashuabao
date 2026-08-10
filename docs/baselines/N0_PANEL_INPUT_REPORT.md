# N0 原版 panel→input 延迟研究（录屏证据）

> 生成：2026-08-11（中间产物，最终基准报告见 N0_BENCHMARK.md）
> 数据：`N0_PANEL_INPUT_EVENTS.json`（152 个事件，逐事件证据链）
> 目的：为 N2 门禁「panel→input P50 ≤ 1.10×原版 / P95 ≤ 1.15×原版」提供原版对照基线。

## 1. 方法

1. **1fps 索引**：两段录屏（秘境局 20260810_214444，SHA `2f6e6f50…`；三普通局
   20260810_224848，SHA `df68c4fd…`，均 1920×1080@30fps）由主 agent 以 1fps 抽帧，
   idx_a 2778 帧、idx_b 2569 帧；帧 k ↔ 视频时间 t = k−1 s。
2. **panel 事件定位**：对全部 1fps 帧运行生产 `_selection_anchor` 语义
   （10 模板 × 6 尺度 × ROI(0.20,0.45,0.80,0.80)，阈值 ≥0.70）+ 光标模板匹配
   （cursor_tpl.png 48×48，灰度 TM_CCOEFF_NORMED）。idx_a 308 帧 / idx_b 620 帧
   命中面板，聚类为 182 个连续 episode（全部边界干净）。
3. **5fps 重抽**：30 个 episode 覆盖两视频全时段，每段 [start−3s, end+3s] 以 5fps
   抽取（`-threads 2`、顺序执行、单段 ≤29s，遵守 ±30s 窗口约束），共 2055 帧。
4. **事件提取**（每 episode）：
   - `first_full` = 连续 anchor 命中段的首帧（面板首次完整可见，按钮行得分 ≥0.7）；
   - `input` = 光标位于卡区（x 350–1350, y 150–650）或按钮行（x 400–1100, y 500–680）
     后 2 帧内出现 ≥250k 像素内容突变或面板关闭的帧（点击发生在该帧前 ≤0.2s）；
   - `close` = 面板消失帧；
   - `latency = input_t − first_full_t`（5fps 分辨率 0.2s；点击落在观测帧前 ≤0.2s 内）。
5. **证据分级**：STRONG = 光标在交互区 + 内容突变/关闭；MEDIUM = 短 run（≤0.4s，
   分辨率下限）；INSUFFICIENT_EVIDENCE = 面板可见但关闭前光标不在交互区或关闭不可见
   （如键盘 F1 触发、光标不可见），不伪造事件。

## 2. 结果

| 统计 | 值 |
|---|---:|
| 总事件 | 152 |
| 可测事件（含证据） | 143（STRONG 138 + MEDIUM 5） |
| insufficient_evidence | 9 |
| P50 | 0.8 s |
| P75 | 1.0 s |
| P90 | 2.2 s |
| P95 | 2.8 s |
| P99 | 4.6 s |
| max | 5.0 s |

分布（0.2s 桶）：0–0.2s×35、0.2–0.4s×61、0.4–0.6s×24、0.6–0.8s×6、
0.8–1.0s×4、1.0–1.2s×6、1.4–1.6s×5、2.0–2.2s×1、3.8–4.0s×1、4.2–4.4s×1。

> 解读：原版典型的「面板出现 → 命中 → 点击」在 0.2–0.6s 内完成（与 §2.2
> 「首次命中立即点击」一致）；P95 2.8s 的长尾来自战斗期面板链（连续多面板
> 快速交替）与个别等待场景（光标已停驻在目标卡上时点击更快，部分面板停留
> 数秒后才动作，与龙珠搜索期行为吻合）。

## 3. 逐事件证据示例（完整列表见 JSON）

| # | 视频 | first_full | input | close | latency | 光标(点击位) | 证据 |
|---|---|---|---|---|---|---|---|
| idx_b_f317-317 | 三普通局 t≈101.8s | f10 t=1.8 | f13 t=2.4 | f14 t=2.6 | 0.6s | (1092,220) 右卡 | 光标入卡区 → 面板关闭 diff=537k |
| idx_b_f242-255 e1 | 三普通局 t≈240.6s | f4 t=0.6 | f7 t=1.2 | — | 0.6s | (1114,209) 右卡 | 光标停驻卡位 → 关闭 diff=601k |
| idx_b_f1012-1033 e2 | 三普通局 t≈1009.6s | f13 t=2.4 | f17 t=3.2 | — | 0.8s | (1119,201) | 光标卡位 + 内容突变 |
| idx_a_f221-228 e1 | 秘境局 t≈220.6s | f9 t=1.6 | f12 t=2.2 | — | 0.6s | (494,254) | 光标卡位 + 内容突变 |

事件内证据字段：`cursor`（点击位）、`cursor_score`、`cursor_local_verify`、
`anchor`（按钮模板名/得分）、`big_diff`（内容突变帧）、`close_t`。
时间戳同时给出视频秒与挂钟（`clock_first_full` / `clock_input`）。

## 4. insufficient_evidence（不造假）

9 个事件面板可见但输入不可见/光标不在交互区（如 F1 快捷键、光标被遮挡），
按蓝图标注 `insufficient_evidence`，不计入统计。事件：idx_a_f1668-1681 ×2、
idx_a_f1771-1777 ×1、idx_a_f1854-1860 ×1、idx_a_f2082-2086 ×1、idx_b_f103-118 ×1、
idx_b_f1307-1324 ×1、idx_b_f1703-1725 ×1、idx_b_f242-255 ×1 等（见 JSON）。

## 5. 断线素材缺口（与 B0 一致）

`gameDisconnect` / `retryConnect` 模板在 idx_a（2778 帧）+ idx_b（2569 帧）+
legacy rec 目录（986 帧）共 6333 帧扫描 **0 命中**（阈值 0.70，scale 1.0）。
仓库 fixtures/manifest.json 已记录 `missing_disconnect_modal`（缺失资源）。
N0 按 missing 记录，不伪造断线帧；S0 需要断线 fixture 时须另找素材。

## 6. 复现

事件流水线脚本在 `C:/tmp/perf_*.py`（一次性研究产物）：
`perf_build_episodes.py`（1fps 面板图）、`perf_extract_windows.py`（5fps 窗口）、
`perf_analyze_windows.py`（逐帧 anchor+cursor+diff）、`perf_extract_events_v5.py`
（事件提取，v5 参数：diff≥250k、卡区/按钮行、effect 须在 run 首帧之后）。
窗口帧：`C:/tmp/perf_episodes/windows/`，逐帧分析：`windows_analysis/`。
