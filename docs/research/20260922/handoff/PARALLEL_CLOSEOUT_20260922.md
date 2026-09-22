# 09-22 并行收口任务单

核对时间：2026-09-22 下午。Owner 派发 agent；主架构负责主目录、合并、身份、门禁和快速测试入口。

## 当前基线与调度

- 主目录 `G:\刷刷宝\GameScript-Local`：开发分支 `fix/hitch-goal-archaeology-20260920`，HEAD `9ed8b52979f4192de9b3a3ac90e3974a9ae3eeec`，工作区干净。
- 打包 worktree `G:\刷刷宝\Worktrees\ui21-hitch-internal-pilot-20260922`：同 SHA，detached HEAD，工作区干净。
- 打包的 16:21–16:41 构建退出 1，pytest 2474 passed / 11 failed / 2 xfailed / 7 skipped；其他三阶段 PASS。随后 pytest 定位轮仍在跑。本次新包尚未交付。
- 32/32 外部输入存在且 SHA-256 与 inputs_manifest.txt 一致；Boss fixtures 有 10 张。此检查不代表全部运行环境一致。
- 打包线继续独占重型计算；并行线仅做读证据、代码审查和准备小范围补丁。不得并跑全量门禁、打包、OCR 批处理或实机。
- 本次打包固定 9ed8b52。后续机制/计分补丁进下一候选，不反复追赶正在构建的 SHA。

## 发给当前正式版打包 agent：失败定位补充

继续完成你当前的 `9ed8b52` internal-pilot 任务；保留当前运行与完整日志，不重复启动第二套全量测试。

主架构已只读核对：32 项输入哈希一致，10 张 Boss 帧存在。你 worktree 的 `.pytest_cache/v/cache/lastfailed` 当前列出 11 项，集中在以下四个文件的实时 OCR 用例：

- `tests/test_attribute_bonds_whitelist_20260914.py`：1 项；
- `tests/test_hitch_archive_challenge_20260914.py`：3 项；
- `tests/test_solo_fengshen_roushen_20260915.py`：2 项；
- `tests/test_solo_main_line_close_task_20260914.py`：5 项。

缓存是定位线索，以本轮失败列表和 traceback 为准。当前定位命令 `--tb=no` 无堆栈；列表出来后先对代表性失败做 `--tb=short -rs` 定向复跑，记录 OCR worker 的启动/超时/模型加载结果、解释器、cwd，以及安全的 OCR 配置项。不要输出卡密、token 或完整环境变量。

对照主目录同 SHA 门禁曾通过，优先排查运行环境、OCR 子进程、缓存/资源与超时，不预设根因。7 个 skip 必须列出原因并解释为何多于已知 2 个；不得靠 skip/xfail、修改 baseline 或 -SkipGate 放行。若缺原帧，只能复制同源原件并记录哈希。

确定性失败若需改生产代码，提交根因和最小修复建议交主架构，不在 detached 打包树里改业务。修复环境后再完整门禁、构建 -NoDeploy、两次 frozen harness、最终 EXE TLS、UI/hash、签名完整性核验。

产出 source_sha / canonical release_manifest_sha256 / channel 三元组、EXE SHA、产物路径、完整日志与失败归因。current.json、正式快捷方式、Grok 登记仍按既定 Owner 授权边界。

## 发给原机制/决策规格 agent：收成可实施规格

你负责 `G:\刷刷宝\_facts_20260922\solo_strategy\` 下新增 `SOLO_IMPLEMENTATION_READY_V1.md`，并在原研究交付目录补充证据勘误。仓库只读，不改配置、生产代码或其他 agent 的文件。你不是唯一在工作的人，保留既有交付，不覆盖其他人的修改。现在不跑 OCR 批处理、全量测试或实机。

输入：当前主目录 9ed8b52、SOLO_DECISION_SPEC_DRAFT.md、SOLO_MECHANICS_FACTS.md、COMPETITOR_SOLO_DECISIONS.md、treasure_debuff_frames/report.md 与 treasure_catalog.md、TASK_H_OBSERVATION_RUN_20260920.md。Owner 已同意建议方向；把有精确依据的规则收口，未定数值保留现状，不自行升级成新批准。

必须完成：

1. 每条待实施规则给出：现有行为及当前 file:line、拟议行为、依据等级、n 的确切含义、测试输入/预期、依赖是否满足。研究里的“有该卡”“有负面分诊”不等于生产夹具已入库。
2. 修正 D6/D7/D12 分类：纯 note/描述勘误可单列；`生命 need 4→3` 属于运行配置变化，追到实际消费者与回归用例。生命证据标明卡头进度/need 与卡名分别是什么。
3. 核对 D10：当前 `_bond_step_blocked` 按 `_bond_next_price()` 判断支付能力；不要把 `<300 禁 F` 当既有游戏事实。区分实际抽价、保留木材、面板调度让位阈值。未批准的新数值不进入首批实施。
4. D1 不能只看“>=8 抢占”：同时核对后续 `_skill_backlog_force()` 抢占分支、visit cap、宝物防饿死。核实 TASK_H 是否已有有效 shadow/choice 基线；给实际路径和样本量，找不到写 NOT_FOUND。不以 hitch 45 段替代完整 solo 对照基线。
5. 宝物逐卡列出“当前 negative_names / patterns 命中、原帧路径、仓内 panel_*.png、DESCRIPTIONS/INDEX、缺口”。重点核实报告声称“诅咒之力已入库”与主目录实际情况；存疑卡保持 uncertain 标签，默认跳过策略与机制事实分别写。
6. 竞品每条可采纳结论补 n 与采样单位，保留竞品≠游戏事实边界；09-17 五条结论给可定位 file:line。
7. 首批实施切分保持唯一 L1 agent 串行：羁绊→宝物→黑商→节奏。证据不足的阶段明确 HOLD，不并发改 choice_policy/mediator。可先准备后续阶段原帧清单和测试方案。

交付 PASS/HOLD/FAIL、具体数字、证据路径、唯一 L1 agent 可直接执行的首批提示词。禁止重新产出一份只有建议、没有输入输出与验收判据的长综述。

## 发给原 Boss agent：历史链路只读复核

修复已经合入主目录 9ed8b52；你只负责历史 bundle 的证据复核，输出到 `G:\刷刷宝\_facts_20260922\mechanics_solo\BOSS_HISTORICAL_RECHECK.md`，不写生产代码、不启动实机、不重跑全量 OCR 或门禁。不要把其他人的文件还原或覆盖。

输入：`G:\刷刷宝\captures\hitch_lobby_chain_20260922_004851_422384` 的 trace、manifest、anomaly 前后原帧，以及既有 `docs/BOSS_CHALLENGE_20260922.md`。

按局列时光之穴和传家宝两条独立链：是否打开列表、识别/点击目标、点击前后原帧、结果可见性、为何跳过。每行给 frame/trace 行号、证据等级；无法认定写 UNKNOWN。特别复核过去“时光之穴 0 成功/7 跳过/3 空滚”和“传家宝 1 成功/7 异常”的分母、互斥关系及遗漏局，禁止把同一局的两个事件简单相加当 10 局。

输出：哪些异常与 f0310 案例同根因、哪些是独立故障、下一次实机最小验收集。新根因不确定就不改行为。历史帧只能说明旧问题，不能证明 9ed8b52 修后实机已通过。

## 主架构承担

- 保持主目录干净、核验打包回传与合并队列。
- 13 号计分缺口已经定位：`tools/live_scenario_capture.py:1234` 的 `max(3, ...)`；`require_archaeology=True` 时 checkpoint 初始化仍为 NOT_REQUIRED（1270）。后续修复限 observer/计分和对应测试，不触碰生产 FSM、不改旧 bundle 原始结果。
- 下一轮计分验收需覆盖配置 1/3/30 局、arch 未确认不得 PASS、manual/fail/bookmark 仍阻断 PASS。当前 5 局已有测试不能覆盖 1 局缺陷。
- 快速入口尚缺 UAC 正常路径验收；当前暂不开实机，等打包释放机器后安排窗口级验证。真正游戏链按 Esc 继续搜房、Boss 后置、单人局内顺序验证。
- 离线通过与修后实机通过分别记账。旧 8880e48 包仅作历史已验证产物。
