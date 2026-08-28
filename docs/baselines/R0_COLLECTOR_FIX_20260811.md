# R0 采集工具修复：SHA/pHash 去重 + 独立 episode + 内容验证（R0-COLLECTOR-FIX）

> 日期：2026-08-11　分支：`codex/ocr-hybrid`　基线：db73fd9（本修复验证时 HEAD）
> 依据：docs/SCOPE_OVERRIDE_1600X900_20260811.md 即时指令第 4 条
> （“R0 collector 仅按文件数量和文件名解锁，缺少 SHA/pHash 去重、独立 episode 和内容验证”）。
> 范围：`tools/collect_machine_material.py`（O4-FIX/R0-FIX/OCR-BLIND 文件所有权隔离：本文件仅属 R0-FIX）。
> 冻结保持：不修改 mediator.py / scenes.json / settings.py / 输入执行器；不接线 O4/P0；零游戏输入。

## 1. 结论

collector 已从“按文件数 + 文件名解锁”升级为**内容驱动解锁**：

1. **SHA256 去重**：字节级相同帧只计 1（重复帧折叠进所属 episode，`duplicate_count` 显式记录）；
2. **pHash 相邻去重**：64bit DCT 感知哈希，海明距离 ≤ `--phash-hd`（默认 10）的相邻帧合并为同一
   episode（jitter/近重复帧不单独计数）；
3. **独立 episode 判定**：同目录内按文件名自然序 phash 聚类；同一面板静止持续期只计 1 个 episode，
   记录 start/end 帧、帧数与持续时长（idx 帧名 1fps 时 duration = 末帧序号 − 首帧序号 + 1）；
4. **内容验证**：面板 crop 区（x 0.24-0.76, y 0.16-0.66，与生产 `_panel_roi_region` 同框）灰度
   std ≥ `--content-std`（默认 18.0）**且** Canny 边缘像素 ≥ `--text-pixels`（默认 500）才算有效
   episode；纯背景/空 crop 判 invalid，**不凭文件名解锁**；
5. **分辨率门禁**：目标窗口分辨率 1600×900 ±20×40 px（实测窗口捕获 1586-1616 × 886-935 全族）；
   960×540 → `NOT_APPLICABLE`（SCOPE_OVERRIDE：游戏无此分辨率），1920×1080 全桌面帧等一律
   NOT_APPLICABLE 不入计数；
6. **门禁计数** = 每类**内容验证通过的去重 episode 数**（≥10）＋ 断线命名帧 ≥1。

## 2. 改动文件

| 文件 | 改动 |
|---|---|
| `tools/collect_machine_material.py` | 新增 phash_bits/phash_hamming/validate_panel_content/_natural_key；scan_frame_dir 重构为 分辨率门禁→SHA 去重→phash episode 聚类→内容验证；Episode 数据类（帧段/时长/SHA/验证结果）；CheckResult 增加 class_dirs/episodes/per_class_episodes；CLI 新增 `--want/--tol-w/--tol-h/--phash-hd/--content-std/--text-pixels`；GUIDE 与检查表更新为 1600×900 口径 |

未触碰：生产代码（src/）、其他工具、fixtures、既有文档。

## 3. 验收演示（构造同内容多文件 + 空 crop 证明计数正确）

素材（离线构造，非新采集）：`C:/tmp/r0_dedup_demo/`
`1600x900/skill/`：panel_A（真实技能面板 1610x935）+ 同名复制（SHA 相同）+ jitter 加噪复制
（σ=2，pHash 近重复）+ panel_B（真实羁绊面板 1595x927，不同内容）+ blank（纯灰 1600x900，
空 crop）+ 960×540 缩放帧 + 1920×1080 缩放帧；`bond/` 2 帧；`treasure/` 1 帧；`disconnect/`
gameDisconnect 命名帧 1 张。

运行：`.venv\Scripts\python.exe tools\collect_machine_material.py --root C:\tmp\r0_dedup_demo --json`

结果（节选，完整 JSON 见运行输出）：

```
skill  validated_episode_count=2  dups=1  na=2
  ep[panel_20260810_100000_a1.png..panel_20260810_100002_a3_jitter.png] frames=2 dup=1 valid=YES (std=41.3 edges=50114)
  ep[panel_20260810_100010_b1.png] frames=1 valid=YES (std=32.3 edges=37832)
  ep[panel_20260810_100020_blank.png] frames=1 valid=NO (std=0.0 edges=0) content_check_failed
  NA: panel_20260810_100030_960x540.png (960x540) note=not_applicable_960x540
  NA: panel_20260810_100031_1920x1080.png (1920x1080)
bond  validated_episode_count=1  dups=0  na=1
treasure validated_episode_count=1  dups=0  na=0
disconnect named: 1
gates: per_class_1600x900_episodes_ge10={skill:2,bond:1,treasure:1} disconnect_frames_ge1=1 ready=False
```

判定：
- 7 个文件（a1 + 复制 + jitter）→ **1 个 episode**（SHA 去重 1 份 + pHash 近重复并入），
  面板 B 单独 1 个 episode → 计数=2 而非 3/7；
- blank 空 crop：std=0、edges=0 → **内容验证失败，不入计数**；
- 960×540 与 1920×1080 → **NOT_APPLICABLE，不入计数**；
- `--check` 退出码 1（素材未齐）——门禁不再被文件数/文件名解锁。

idx 帧名 episode 时长验证（`C:/tmp/r0_dur_demo`，000100-000105 同面板静止 + 000200 新面板）：
```
ep[000100.png..000105.png] duration_s=6.0 n_distinct_sha=2 frame_count=2 dup=4 valid=YES
ep[000200.png] duration_s=None
```
000100-000105 六帧（5 帧字节相同 + 1 帧 jitter）合并为 1 个 episode，时长 6s（1fps），4 份 SHA
重复帧折叠——满足“同一面板静止持续期只计 1 个 episode；jitter 帧不单独计数”。

## 4. 命令

```bat
:: 指引 + 检查表（1600×900 口径）
.venv\Scripts\python.exe tools\collect_machine_material.py
:: JSON（含每 episode 帧段/SHA/时长/内容验证）＋ 门禁退出码
.venv\Scripts\python.exe tools\collect_machine_material.py --root <素材根> --json --check
:: 调参（分辨率容差 / phash 阈值 / 内容验证阈值）
.venv\Scripts\python.exe tools\collect_machine_material.py --want 1600x900 --tol-w 20 --tol-h 40 --phash-hd 10 --content-std 18.0 --text-pixels 500
```

## 5. 与 SCOPE_OVERRIDE 的一致性

- 960×540 不再出现于采集目标与门禁；明确 NOT_APPLICABLE（`not_applicable_960x540` 标注）；
- 不接受缩放伪造（分辨率门禁硬校验窗口捕获尺寸）；
- 其余分辨率（1366×768/1280×768/1024×768/1680×1050）同样 NOT_APPLICABLE，不阻塞首发。

## 6. 风险与后续

- 素材根目录尚无 10/类 的 1600×900 episode：`ready=False` 是**真实缺口**（需实机采集），
  非工具缺陷；与 O3 门禁一致的 BLOCKED 状态继续有效；
- pHash 阈值 10 与内容验证阈值（std 18/边缘 500）为实测标定值（真实面板 std≈32-48、边缘
  3.7 万-5 万；纯背景 0），可按素材形态微调；
- episode 时长仅对数字命名帧（idx 1fps 惯例）有意义；非数字命名返回 null（帧数仍记录）。
