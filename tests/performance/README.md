# tests/performance —— N0 热路径基准 fixtures 与说明

> 属于任务包 N0（PERF-BASE）。仅本目录与 `tools/benchmark_hot_path.py`、
> `docs/baselines/N0_*` 属 PERF-BASE 所有权；不修改生产代码。

## 用途

`tools/benchmark_hot_path.py` 对 `fixtures/manifest.json` 中每个 fixture 帧按
三种模式（cold / warm-changed / exact-static）复现生产热路径：

- capture（帧解码代理）+ health + context + decision + action 分阶段耗时；
- `cv2.matchTemplate` 调用次数与搜索像素总量（进程内包装计数）；
- 环境记录（Python/OpenCV/CPU/分辨率/commit）+ assets/Images 模板聚合 SHA256；
- 输出 `docs/baselines/N0_BENCHMARK.json` + `.md`，同一命令可重跑。

## 运行

```powershell
.venv\Scripts\python.exe tools/benchmark_hot_path.py            # 全部 fixture，每模式 3 次
.venv\Scripts\python.exe tools/benchmark_hot_path.py --fixture idle_hud --iterations 1
```

退出码 0 = 成功；fixture 读取失败退出码 2。

## 十二类覆盖（蓝图 §6）

| class | fixture_id | 来源 | expected context |
|---|---|---|---|
| 空闲 HUD | idle_hud | fixtures/replay/main_line_auto_on.png | MAIN_LINE |
| 技能 | skill_panel | fixtures/replay/skill_choice_3.png | MAIN_LINE |
| 羁绊 | bond_panel | fixtures/replay/bond_choice_3.png | MAIN_LINE |
| 宝物 | treasure_panel | fixtures/replay/treasure_choice_3.png | MAIN_LINE |
| 胜利 | victory | fixtures/replay/victory_continue.png | MAIN_LINE |
| 失败+面板 | fail_panel | rec_fine_bug/bug_00007.jpg（秘境局 t=2083s） | MAIN_LINE |
| giveUp+面板 | giveup_panel | idx_b/000105.jpg（三普通局 t=104s） | MAIN_LINE |
| 断线 | disconnect_modal | 素材缺失（6333 帧扫描 0 命中，见 manifest notes） | QUIT（missing） |
| stage | stage_select | fixtures/live_postgame_20260808/live_stage_select.png | STAGE_SELECT |
| 房间 | room_waiting | fixtures/replay/room_waiting_host.png | ROOM_WAITING |
| unknown | unknown_page | fixtures/unknown_page.png | UNKNOWN |
| 黑屏 | black_frame | fixtures/black_frame.png | UNKNOWN（健康门禁拦截） |

所有存在文件的 fixture 均已用生产管线验证 expected context（见 manifest；
`N0_BENCHMARK.json` 中 `context_verified` 为运行期逐项核对结果）。

## 复现性与门禁

- 三次连续运行中位偏差 ≤10%（以 warm-changed idle_hud P50 为准）；
- 报告含 commit、环境、模板聚合 SHA、P50/P95、匹配次数、搜索像素；
- 黑屏类 fixture 期望被健康门禁拦截（decision=0），属正常语义。

## 视频侧（panel→input 延迟）

见 `docs/baselines/N0_PANEL_INPUT_EVENTS.json`（143 个可测事件，P50=0.8s /
P95=2.8s，5fps 窗口分析）与 `N0_PANEL_INPUT_REPORT.md`。流水线脚本位于
`C:/tmp/perf_*.py`（一次性研究产物，证据 JSON 已入库）。
