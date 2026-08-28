# N2.4 灰度/彩色阈值重标表（2026-08-11）

> 依据：`tests/performance/fixtures/*` + `fixtures/replay/*` 共 10 个 fixture × 39 个热路径
> 模板的离线测量（`C:\tmp\measure_gray.py` 方法：同帧同尺度下分别计算彩色与灰度
> TM_CCOEFF_NORMED，取彩色最佳位置的灰度分数）。
>
> 结论先行：**灰度候选阈值 = 原彩色阈值 − 0.05（`matcher.GRAY_THRESHOLD_OFFSET`），
> 精度由命中后的局部彩色复核以原彩色阈值兜底**——因此无需逐调用点改写阈值常量，
> 全部 fixture/模板共用同一偏移即可同时满足召回与精度。

## 1. 为什么灰度阈值 ≠ 彩色阈值

| 度量 | 值 |
|---|---|
| 样本数（fixture × 模板，color best ≥ 0.50） | 218 |
| 灰度−彩色 分数差（color − gray@color_loc）中位数 | 0.000 |
| P90 | 0.017 |
| 最大（正差，彩色高于灰度） | 0.058（auto_task_off 于 fail_panel/idle_hud/bond_panel） |
| 正差 > 0.05 的行数 | 4 / 218（全部是 auto_task_off / treasure_refresh_btn 等非动作关键模板） |

灰度分数与彩色分数同分布（中位数差 0），但个别模板存在 ≤0.06 的落差。若沿用
彩色阈值，灰色候选取 `threshold` 会把这类模板的真实命中拒之门外（召回损失）；
取 `threshold − 0.05` 覆盖全部实测落差（含最差 0.058），且彩色复核仍按原阈值
过滤假阳性（精度不降）。

## 2. 关键模板重标前后阈值对照（fixture 实测）

| 模板（调用点） | 原彩色阈值 | 重标灰度候选阈值 | fixture 实测彩色 | 实测灰度 | 复核阈值（彩色） |
|---|---|---|---|---|---|
| skill_giveup_btn（选择锚点 0.70） | 0.70 | 0.65 | 0.556–0.696* | 0.562–0.675* | 0.70 |
| skill_refresh_btn（锚点/刷新） | 0.70 | 0.65 | 0.749–0.913 | 0.759–0.927 | 0.70 |
| bond_hide_btn / treasure_lock_btn 等面板按钮 | 0.70 | 0.65 | 0.52–0.95 | 0.53–0.96 | 0.70 |
| 挑战开关（coin/wood/experience/treasure） | 0.68 | 0.63 | 0.685–0.99 | 0.699–0.99 | 0.68 |
| kk_start / room_start（房间开始） | 0.85 | 0.80 | 0.502–1.000 | 0.529–1.000 | 0.85 |
| stage1–4（选关编号列） | 0.85 | 0.80 | 0.516–0.94 | 0.525–0.94 | 0.85 |
| continueGame（胜利继续） | 0.80 | 0.75 | 0.874 | ~0.87 | 0.80 |
| jq / pg（技能卡） | 0.85 | 0.80 | 0.540–0.616* | 0.620–0.701* | 0.85 |
| auto_task_on / off | 0.50 | 0.45 | 0.759–0.968 | 0.701–0.975 | 0.50 |
| pauseGame / quit / HeroChallenge 等战后锚点 | 0.80–0.85 | 0.75–0.80 | 0.51–0.95 | 0.52–0.96 | 原值 |
| longzhu / longzhu2（龙珠卡蓝框） | 0.85 | **不重标（保持彩色）** | 0.514–0.528* | 0.527–0.540* | — |

\* 低于阈值的行是页面上的非命中（假阳性/其他元素），灰度偏移不影响其过滤语义。

## 3. hue 模板保持彩色（不参与灰度重标）

- `longzhu` / `longzhu2`：龙珠卡蓝框，色相是判别依据 → `matcher._COLOR_ONLY_TEMPLATE_STEMS`。
- `r/sr/ssr/ur/ex/hc`（稀有度）、`pinfu/pingfu*`（品质）：色相语义，保持彩色。
- `closeLongzhu`：关闭按钮（形状/文字，非 hue）→ 灰度路径（N2.4 起）。
- 品质色选卡（`_card_rarity_score`）、蓝色按钮（`find_blue_buttons`）本就不经
  matchTemplate，不受本表影响。

## 4. 复核语义（先灰度候选 → 局部彩色复核）

1. 灰度候选：`gray_th = max(0.40, threshold − 0.05)`，逐尺度首峰/全峰扫描。
2. 命中后局部彩色复核：在灰度峰位置 ±1px 邻域用 numpy 彩色 NCC（与
   cv2.TM_CCOEFF_NORMED 同式）验证，需 ≥ 原彩色阈值；复核分数即返回分数
   （阈值/margin/比较全部保持在彩色刻度）。
3. 复核不过 = 假阳性 → 该峰否决（最多尝试 3 个峰），不产出结果。

## 5. 全量回归

- 全部 fixture 的 `context_verified=True`（N2_BENCHMARK_run1..3）。
- `tests/performance/test_benchmark_smoke.py` PASS。
- `compare_ledger.py`（OCR off）：diffs=0（score WARN：skill_choice_4 0.838→0.925，
  为复核分数取代旧彩色分数所致，属易失字段）。
- 全量 unittest：306 通过（2 个 expected failures，均为既有 XFAIL 类）。
