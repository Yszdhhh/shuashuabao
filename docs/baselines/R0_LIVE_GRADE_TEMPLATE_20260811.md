# R0 实机分级报告模板（R0.2 S1–S4）

> 用途：R0.2 实机分级（蓝图 §15）逐级验收的报告填写模板。实机执行本身 BLOCKED
> （待用户素材与 S0 恢复证据），本文件只定义"执行前准备 → 执行步骤 → 证据字段 →
> 通过判据 → 报告填写模板"。任何一级未运行前不得声称通过。
> 前置门禁（未满足不得开跑对应级别）：S1 需 S0 恢复路径单元证据 + 回放回归集全绿；
> S2 需 S1 通过；S3 需 S2 通过；S4 需 S2 通过（故障注入可在 S2 之后任一监督窗口内补做）。

## 0. 报告头部（每级填写一次）

```text
级别: S1 / S2 / S3 / S4
日期: YYYY-MM-DD
分支/HEAD: codex/ocr-hybrid @ <commit>
执行人/观察员: <谁在场监督>
EXE SHA256: <dist_release2\GameScript\*.exe 或指定构建>    sidecar SHA: <...>    模型 SHA: <...>
配置 SHA / 关键开关: <config/*.json sha>  ocr_mode=off|shadow  dry_run=false
游戏窗口分辨率: 1600×900 / 960×540 / 1920×1080
incident 目录: %LocalAppData%\GameScript-Local\incidents\（S0.5 接线后）
panel_sample 目录: %LocalAppData%\GameScript-Local\YYYYMMDD\panels\
录屏文件: <路径 + SHA256 前 16 位 + 分辨率 + 时长>（录屏抽帧不得与实机压测并行）
```

## 1. S1 监督运行 3 局（错误输入 0，闭环 3/3）

### 1.1 准备
- 回放回归集（fixtures/manifest.json + fixtures/scenarios）全绿；ledger 与基线零 diff；
- 确认生产配置：`ocr_mode=off`（或 shadow，登记开关组合）；dry_run 已关闭；
- 建房→进局→主线→退出→回房的正常闭环路径所需场景/模板已就位（stage、HUD、QUIT、回房）；
- 监督环境：观察员在场；录屏开启；incident 目录已接线；急停键/终止方式确认可用。

### 1.2 执行步骤
1. 启动带 panel_sample 的构建，进入大厅建房（或复用既有房间）；
2. 进入第 1 局：记录 进局时间戳 / 局内全部动作 tick 的 trace；
3. 完成主线（含技能/羁绊/宝物面板选择）至局末：胜利或失败路径；
4. 退出 → 回房；重复共 3 局；
5. 每局结束立即导出：trace JSONL、incident 目录、panel_sample 目录、截图集。

### 1.3 证据字段
| 字段 | 来源 | 说明 |
|---|---|---|
| trace | `%LocalAppData%\GameScript-Local\YYYYMMDD\trace_*.jsonl` | 每 tick context/phase/decision/action/ocr_mode |
| incident | `%LocalAppData%\GameScript-Local\incidents\YYYYMMDD\incidents\` | unknown/异常页归档（frame_before/now/after + metadata.json） |
| ledger | `tools/run_replay.py --ledger <path>` 或实机动作日志 | 实机动作序列（与回放 ledger 同字段口径） |
| 截图 | 每局关键节点（面板/失败/退出确认）全帧 PNG | 与 trace 时间戳对齐 |
| 时长 | 每局 start→exit 挂钟时间 | 供 S2/S3 时长折算 |
| 局数 | 本级别 3 局（第 1 行"执行人"栏记录） | 闭环计数用 |

### 1.4 通过判据（全部满足才算 S1 PASS）
- 3/3 局闭环：建房→进局→主线→后段→退出→回房 无人工干预完成；
- 错误输入 0：无"失败画面继续选卡"、无关卡串位、无对 unknown/黑窗/陈旧缓存的输入；
- 任一 tick 最多一个输入；每次 UI-changing 输入后画面变化或后置锚点确认；
- 单局 hard deadline 与面板 deadline 未被动作续期（trace 可证）；
- 全程无崩溃；`panel_sample` 目录出现面板帧（旁路证据，无输入权）。

### 1.5 S1 报告填写模板
```markdown
## S1 报告（3 局监督）
| 局 | 进局 | 退出 | 闭环 | 错误输入 | trace 文件 | incidents | 截图 |
|---|---|---|---|---|---|---|---|
| 1 | <ts> | <ts> | 是/否 | 0/N | <路径> | <n> | <路径> |
| 2 | … | … | … | … | … | … | … |
| 3 | … | … | … | … | … | … | … |
结论: PASS / FAIL / BLOCKED（缺任一证据字段即 BLOCKED，不得用"基本通过"）
```

## 2. S2 无人值守 10 局或 ≥2 小时（不卡死、无人工救场）

### 2.1 准备
- S1 通过；`cycle_num` 配置 ≥10（或按 2h 时长折算）；
- 无人值守运行方式确认：进程看护（崩溃自动重启可选）、录屏全程、观察员不得干预输入；
- 状态停滞 watchdog 与 hard deadline 已生效（配置登记）；网络保持稳定（本级别不注入故障）。

### 2.2 执行步骤
1. 启动构建，记录启动时间戳与配置 SHA；
2. 进入自动循环（建房→进局→主线→退出→回房），期间无人输入；
3. 每局结束记录 outcome（VICTORY / FAILURE / TIMEOUT / DISCONNECT）与局数计数；
4. 到 10 局或 ≥2h 停止（cycle_num 精确停止，绝不点击下一局开始）；
5. 全程录屏 + trace + incident + panel_sample 归档。

### 2.3 证据字段
| 字段 | 来源 | 说明 |
|---|---|---|
| 局数/时长 | 启动→停止挂钟 + 每局 outcome 计数 | 10 局或 ≥7200s |
| 卡死检测 | watchdog 日志 + trace 中停滞 tick 区间 | 无状态停滞 >60s 无 recovery/QUIT/ERROR |
| 人工救场 | 观察员记录（无输入即 0） | 0 次 |
| 内存/CPU | 进程 RSS 采样（斜率 ≤50MB/小时） | 核心进程无崩溃 |
| trace/incident/ledger/截图 | 同 S1 字段 | 全程 |
| panel_sample | `panels\` 日目录帧数与 960×540 帧数 | 顺带完成素材收集 |

### 2.4 通过判据（全部满足才算 S2 PASS）
- 10 局或 ≥2h 无人工救场；无卡死（>60s 停滞必须有 recovery/QUIT/ERROR 记录）；
- 核心进程无崩溃；内存增长斜率 ≤50MB/小时；
- 连续 3 局失败自动停止（若发生，如实记录并 FAIL）；
- 任何错误点击 / 失败画面继续选卡 / 关卡串位 = 0；
- 录屏抽帧不得与本次压测并行。

### 2.5 S2 报告填写模板
```markdown
## S2 报告（无人值守）
- 运行窗口: <start_ts> ~ <stop_ts> = <时长>；局数 <N>
- 每局 outcome: VICTORY×a / FAILURE×b / TIMEOUT×c / DISCONNECT×d
- 卡死: <停滞区间列表，或 0>
- 人工救场次数: <0 或记录>
- 内存: <起止 RSS / 小时斜率>；崩溃: <0 或记录>
- 错误输入: <0 或记录>
- trace/incident/ledger/截图/panel_sample 路径清单
结论: PASS / FAIL / BLOCKED
```

## 3. S3 双 session 累计 30 局或 ≥6h（跨 session 长稳）

### 3.1 准备
- S2 通过；至少两个独立 session（不同进程/不同登录窗口或不同日期），各自独立配置 SHA 记录；
- 两个 session 不得共享同一 trace/incident 目录（各自 `YYYYMMDD` 或独立子目录）。

### 3.2 执行步骤
1. Session A 启动（记录配置 SHA / 窗口分辨率），按 S2 流程跑；
2. Session B 在独立时间窗启动（可与 A 不同分辨率，建议一 1600×900 一 960×540 顺带采集）；
3. 累计 30 局或 ≥6h；每 session 独立记录 outcome/卡死/救场/内存；
4. 结束后合并统计（只合并计数，不合并 trace 文件）。

### 3.3 证据字段
- 同 S2 全套，按 session 分组；
- 附加：两 session 的 配置 SHA、窗口分辨率、启动/停止时间、各自局数与时长；
- 若任一 session 为 960×540：panel_sample 的 960×540 帧计入素材到位检查表。

### 3.4 通过判据（全部满足才算 S3 PASS）
- 双 session 累计 ≥30 局或 ≥6h，各自满足 S2 判据；
- 每 session 无人工救场、无卡死、无崩溃、错误输入 0；
- 内存斜率 ≤50MB/小时（逐 session）；
- 跨 session 无共享状态污染（ledger 语义一致，compare_ledger 等价）。

### 3.5 S3 报告填写模板
```markdown
## S3 报告（双 session）
| session | 配置 SHA | 分辨率 | 窗口 | 局数 | 时长 | 卡死 | 救场 | 崩溃 | 错误输入 |
|---|---|---|---|---|---|---|---|---|---|
| A | <sha> | 1600×900 | <ts>~<ts> | <n> | <h> | 0 | 0 | 0 | 0 |
| B | <sha> | 960×540 | <ts>~<ts> | <n> | <h> | 0 | 0 | 0 | 0 |
累计: <30 局或 ≥6h>　结论: PASS / FAIL / BLOCKED
```

## 4. S4 人为故障注入（失败/断线/unknown 恢复或安全停止）

### 4.1 准备
- S2 通过；S0 恢复路径单元证据齐备（RECOVER_FAILURE、断线独立恢复脚本、unknown 有界零输入）；
- 故障注入手段：失败（自然或脚本触发）、断线（断网/关服务端/`tools/net_block.py`）、
  unknown（切换错误窗口/遮挡窗口）；
- 每次注入前记录基线：正常局闭环一次 + trace 采样。

### 4.2 执行步骤
1. 失败注入：正常局内触发失败（或等待自然失败），观察恢复脚本 ≤3 次尝试/间隔 ≥1.5s/总期限 60s；
   恢复完成后进入 QUIT；记录 fail 锚点帧与面板并存时的抢占行为；
2. 断线注入：运行中断网（推荐 `tools/net_block.py watch` 自动阻断+抓屏检测），
   验证走断线恢复路径而非 fail 路径；重连或安全停止；记录真实断线弹窗帧
   （命名 gameDisconnect/retryConnect 落入素材根目录）——即 O3 BLOCKED 项补证据；
3. unknown 注入：切换到未知页面/黑窗，验证 0 输入 + 有界退出（unknown 超时 → QUIT/ERROR）；
4. 每次注入记录：注入时间、恢复路径、动作序列、期限消耗、最终状态（恢复/QUIT/ERROR）。

### 4.3 证据字段
| 字段 | 来源 | 说明 |
|---|---|---|
| 注入清单 | 本报告 | 每次注入的类型/时间/手段 |
| trace | 注入窗口 trace JSONL | 恢复脚本每步：锚点+输入+画面变化/后置确认 |
| incident | incidents\ 目录 | 每次注入的 incident 组（frame_before/now/after） |
| 断线素材 | <素材根>\disconnect\gameDisconnect_*.png 等 | 真实断线弹窗帧（≥1） |
| ledger/截图/时长/局数 | 同前 | 恢复期动作序列 |

### 4.4 通过判据（全部满足才算 S4 PASS）
- 失败：≤3 次尝试、间隔 ≥1.5s、总恢复期限 60s 内有界；恢复后进入 QUIT；
- 断线：走断线专用恢复路径（非 fail 路径）；有真实断线弹窗帧证据（命名素材 ≥1）；
- unknown：0 输入 + 有界超时退出（QUIT/ERROR），无死循环；
- 强失败连续两帧后抢占选择面板；giveUp 单独出现且有面板锚点时不判失败；
- 任一恢复动作均有"锚点出现 + 输入成功 + 画面变化/后置锚点"证据链；
- 故障后不崩溃；恢复/停止路径内无错误点击。

### 4.5 S4 报告填写模板
```markdown
## S4 报告（故障注入）
| 注入 | 手段 | 时间 | 恢复路径 | 尝试次数 | 期限消耗 | 最终状态 | trace | incident | 素材 |
|---|---|---|---|---|---|---|---|---|---|
| 失败 | <自然/脚本> | <ts> | RECOVER_FAILURE | ≤3 | <s> | 恢复/QUIT | <路径> | <n> | <帧> |
| 断线 | net_block/断网 | <ts> | DISCONNECT 路径 | ≤3 | <s> | 恢复/QUIT | <路径> | <n> | gameDisconnect_*.png |
| unknown | 错误窗口 | <ts> | 有界超时退出 | 0 | <s> | QUIT/ERROR | <路径> | <n> | - |
结论: PASS / FAIL / BLOCKED（断线素材缺失时该行必须 BLOCKED）
```

## 5. 汇总表与最终发布门禁（S1–S4 全部 PASS 后逐项核对）

| 门禁（蓝图 §15 最终发布） | 证据 | 状态 |
|---|---|---|
| 正常局闭环成功率 ≥95% | S1+S2+S3 汇总 |  |
| 错误点击 / 失败画面继续选卡 / 关卡串位 = 0 | 各级 trace 统计 |  |
| 无状态停滞 >60s；超期有 recovery/QUIT/ERROR | S2/S3 watchdog |  |
| 连续 3 局失败自动停止；cycle_num 精确停止 | S2 outcome 计数 |  |
| 单局 hard deadline / 面板 deadline 不可续期 | trace 期限字段 |  |
| 核心进程无崩溃；内存斜率 ≤50MB/小时 | S2/S3 采样 |  |
| CPU/IO 无持续异常峰值；录屏抽帧不与实机压测并行 | 运行记录 |  |
| EXE/sidecar/模型/配置均有 SHA 与一键回滚 | 报告头部 + git revert |  |
| README 列出已支持与默认关闭模块 | docs 核对 |  |
| 只有 S3/S4 通过后才允许表述"支持长期多局无人值守" | 本表结论 |  |
