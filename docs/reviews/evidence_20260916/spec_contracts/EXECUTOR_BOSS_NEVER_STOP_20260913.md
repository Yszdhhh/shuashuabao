# 执行 Agent 提示词：Boss 找不到时点能点到的最后一张卡，不再停机（2026-09-13）

> 由架构会话编写，规则来自用户。粘贴分隔线以下全部内容给执行 Agent。

---

用户拍板了一条新规则：**战后 Boss（时光之穴、传家宝）找不到目标时，就点当前能点到的最后一张 Boss 卡。任何 Boss 相关的失败都不许停掉整个运行。**

主线：`G:\刷刷宝\GameScript-Local`，分支 `integration/converge-20260912`，也就是 PR #19 的 head。全程中文。

## 0. 并发与时机

- PR #19 在 d41a803 上的 CI 可能还在跑，**不要取消**，它要验证上一轮的 CI 修复。你的新提交推上去后，会自动再触发一轮。
- 开工前先 `git fetch`，确认 `git status --short` 为空，并且本地 HEAD 等于 `origin/integration/converge-20260912`。

## 0.5 先修 CI 剩下的最后一个失败（单独一个提交，只改测试）

PR #19 在 d41a803 上的 CI（run 34741028810）：2106 个通过，1 个失败——`tests/test_hitch_full_natural_e2e.py::test_readiness_keeps_public_backpack_blocked_until_production_gt`，报 `assert 'PRESENT' == 'MISSING'`。

根因（架构会话已核实）：
- 这个文件第 28–29 行，本机上会把 `CANDIDATE_ROOT` 指向旧工作树 `G:\刷刷宝\Worktrees\lobby-hitch-surface-test`。那是 09-09 的旧候选（53afb43），里面还没有 `_maybe_public_backpack_deposit`，所以本机读到的是 MISSING。**本机的绿灯是在测一棵过期的树，是假绿。**
- CI 上没有这个目录，就回退到主线。主线 `mediator.py:5142` 已经有这个入口，readiness 实际报告 `production_entry_status=PRESENT`、`production_readiness=CONDITIONAL`、`production_missing=[]`。

修法：
- 删掉 `_LOCAL_CANDIDATE`，`CANDIDATE_ROOT = ROOT`。收敛之后生产根就是主线本身，同文件另外 3 个 identity 测试也要随之指向主线。
- 这个测试改名为 `test_readiness_reports_public_backpack_conditional_until_production_gt`，断言改成：`production_entry_status == "PRESENT"`、`production_readiness == "CONDITIONAL"`（也就是「真实实机验证之前不算 READY」的原意）、`production_missing == []`，并且和 `TARGET_PRODUCTION_FACTS["public_backpack_deposit"]["production_readiness"]` 一致。
- 本机跑这个文件（8 个用例）全过后单独提交；只改测试，不用重定身份基线，但 lnk 仍要更新。
- 顺带用 `git grep -n "Worktrees" tests/ tools/` 查一下还有没有别的测试写死本机旧工作树路径。有就同样修掉，列进汇报。

## 1. 规则的具体含义

- **顺序定位保留**：目标能直接认出就点；认不出但序号 ≤ 末卡时按顺序推算，在预测格位二次确认后再点；目标序号 > 末卡（没解锁）就点末卡。
- **变化只在「收口」**：凡是原来会走「有界等待 → `set_phase(ERROR)` + `stop()`」的地方，一律改成**点当前画面里能识别出、能点击的最后一张 Boss 卡**。「最后一张」按物理位置取，y+h 优先，其次 x+w；传家宝页面只算序号 1–20 的卡。这包括：
  - 滚动到上限仍未证明到底；
  - 回底预算用完仍未证明到底；
  - L+1 格位有卡但认不出来（先按现有逻辑对 L+1 做预测确认，拿不到证据再点能点到的最后一张）；
  - 定位尝试用尽；
  - `_POST_GAME_BOSS_UNRESOLVED_LIMIT` 次观察后仍然没有结论。
- **一张卡都认不出来**时（没有能点的东西）：**跳过这次 Boss 挑战**，继续战后链的下一步，比如关闭存档面板、关闭传家宝对话框，再继续下一局。可以参考 `mediator.py` 里时光之穴蹭车模式已有的跳过路径（约 14837 行：`_time_cave_boss_done=True` 后落到 `_find_archive_panel_close`），传家宝要找到等价的关闭 / 继续路径。跳过前要有上限（沿用 unresolved 上限），并记一条 incident。
- **防止滥用「跳过」（用户补充，已确认）**：正常每一局，存档挑战、时光之穴、传家宝都**有卡可点**。传家宝**没有**每日次数上限。存档挑战中间四个每天 8 次（面板上显示 x/8），但用户要求**全部照点**：没次数的点了也没有负面影响，**不要为次数新增任何判断**。所以「一张卡都认不出」**一律视为识别异常**：
  - 跳过前必须先做完：鼠标停车（沿用 `act_move` 那套，清掉悬停遮挡）→ 重新截图 → 用更宽的尺度再识别一次，总次数不少于 unresolved 上限的 2 倍。全部失败后才能跳过。
  - 跳过一律记为 `BossChallengeSkipped(reason=anomaly)`，并保存 incident 截图。同一页面连续 2 局发生异常跳过时，看板日志要出现一条 warn 级别的提示，比如「时光之穴连续 2 局没有认出任何卡，请检查分辨率 / 遮挡」，但**仍然不停机**。
  - **不要**做「每日上限」识别，也不要做「今天不再打开传家宝」这类记忆。
- 仍然要守住的底线：**只点击模板或 OCR 实际命中的卡**，不许凭推算坐标盲点（预测格位必须二次确认后才能点）。

## 2. 要改的停机点（行号以当前 HEAD 为准，用函数名核对）

`mediator.py::_maybe_challenge_configured_boss` 里所有 `set_phase(Phase.ERROR, "Boss ...")` + `stop()` 都要改（目前大约在 6978、6990、6996、7003 行），另外还有调用方的非蹭车分支「时光之穴 Boss 兜底选择未确认，Fail-Closed 停止运行」（约 14844 行）。用 `grep -n "Phase.ERROR" src/shuabao/mediator.py` 把所有 Boss 相关的都列出来，逐个改。**与 Boss 无关的 ERROR 路径不要动。**

- `boss_order.py` 中：`LOCATE_FAILURE_FALLBACK_DEFAULT` 固定为 `"last_card"`（用户已确认）。删掉 `fail_closed` 分支和 `FAIL_CLOSED` 动作，或者让它们不可达，同时删掉对应的死代码和测试。
- 日志和动作名要能区分下面几种情况，便于事后在 trace 里统计：
  - `BossConfigured`：点中目标；
  - `BossNotUnlockedLast`：目标未解锁，点末卡；
  - `BossOrderLocateFailed`：定位失败，点末卡；
  - `BossLastVisibleFallback`（新增）：没证明到底 / 末卡不确定，点能点到的最后一张；
  - `BossChallengeSkipped`（新增）：一张卡都认不出，重试后跳过，reason=anomaly。

## 3. 看板

蹭车、跟车、单刷三处的说明文字改成：「找不到时：按顺序定位，仍找不到就选能点到的最后一个」。同步修改 `ui-v2/tests/hitch_config_contract.spec.ts`，然后 `npm run build`。

## 4. 测试

- 纯函数和集成测试覆盖上面每一种收口：各断言一次点击，以及对应的动作名。其中至少各有一例**不 patch** at_bottom、at_top、find，直接走真实夹具。
- 「一张都认不出」：用一张没有任何 Boss 卡的帧（可以把卡片区域涂黑），断言以下几点：
  - 先发生了鼠标停车和重试，次数够了才跳过；
  - 没有点击，`phase != ERROR`，`stop_signal` 未被置位，并且进入了关闭 / 继续路径；
  - 连续 2 局异常跳过时产生 warn 日志。
- 回归：原来断言「ERROR + stop」的 Boss 用例，要改成新行为下的断言，**不许删掉了事**。
- `python tools/release_gate.py`（加超时保护）必须 exit 0。不许改快照，不许 skip。

## 5. 收尾

1. 提交信息先写进文件，用 **UTF-8 无 BOM** 编码（PowerShell 用 `[IO.File]::WriteAllText($p, $msg, (New-Object Text.UTF8Encoding $false))`），再 `git commit -F`。
2. 改了 `src/shuabao`，所以要重定身份基线（`tools/live_harness_identity.py` 和 `tests/test_live_harness_refresh.py`），然后把 Live lnk 的 SHA 改成新 HEAD，运行 identity 确认 `READY FOR GT: YES`。
3. 推送 `integration/converge-20260912`（普通推送，禁止 force），PR #19 会自动更新。用 `gh pr checks 19 --watch` 在后台一次性等待 CI。CI 失败按上一份 PR 提示词第 4 节处理。
4. CI 通过就停下汇报，**不合并**。用户会运行 `/code-review ultra 19` 做云端审查，并决定何时合并。

## 红线

不点开始运行，不产生游戏输入，不跑 Live harness，不打包，不动其他工作树。

## 汇报

①提交 ②改掉的停机点清单（原行号 → 新行为）③每种收口对应的测试名 ④门禁 ⑤身份 READY 和 lnk 的 SHA ⑥CI 结果和 PR 链接。
