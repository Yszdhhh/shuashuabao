# 新会话项目交接（2026-09-24）

写给在新对话（Claude Code Cloud 模式或其它 agent）里接手本仓库的人。旧的 Project 里有共享记忆、多个线程和项目文件，新对话都看不到，所以本文把它们的要点收在这里。**以本文和 git 为准**；如果本文和最新提交冲突，以最新提交和 `docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md` 为准。

## 0. 先读这四份

1. `AGENTS.md`：硬规矩。误点会造成真实游戏后果。
2. 本文。
3. `docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md`：统一分支的组成、待本机验证项、Owner 局内规则锁表。
4. `docs/handoff_20260924/CARD_FAMILY_PICKUP_AUDIT_20260924.md`：各系列卡组拿取的现状和缺口。

`docs/` 下其余按波次堆叠的历史文档（B0–B10、N/S/O/P/G/R）多数已过期，彼此矛盾，不要照着施工。

## 1. 目标和当前优先级

项目：刷刷宝（ShuaBao），给 KK 对战平台上的 War3 自定义地图《重生魔兽刷刷刷》做的 Windows 自动化脚本。流程是截图，再做 OpenCV 模板匹配和 OCR，最后用 SendInput 真实点击。有单刷和"蹭车"两种模式，还有实机测试台和 Web 看板（`ui-v2/`）。

**最高优先级（Owner 09-24）：快速上线。** 先用"模板匹配 + 简单阈值"把现有逻辑跑通。上线前的主线只有四块：

1. 大调度逻辑跑通（L0 大厅 → L1 局内 → 恢复与战后，整局闭环）；
2. 各系列卡组的拿取逻辑跑通（现状见 `CARD_FAMILY_PICKUP_AUDIT_20260924.md`）；
3. 长时间运行兜底（单局 3600s 硬超时、idle 看门狗、每局新建房、失败取证包都已有；缺业务进度看门狗、跨局健康统计、通知）；
4. UI 看板的功能接入和逻辑梳理。

本地看板已收敛成三个：正式版看板、快速测试看板、UI 测试看板。

**上线后再做：** 调度量化，包括动态软阈值、上下文影子价格、48 局 A/B、trace 加字段。材料在 `docs/research/scheduling_20260924/`，GPT 的案头调研在 PR #41。上线前不要推这部分代码。本地测试时可以顺带采数据，但只当后续训练的参考，不是主线。

**提速方向（Owner 09-24）：** 正式版走分级识别：先用卡族名模板秒选，再做局部 OCR，最后全量 OCR 兜底。按卡族名识别，不按卡面识别。测试版可以保留全量识别。

## 2. 仓库、分支和 PR

- 仓库：https://github.com/Yszdhhh/shuashuabao（公开，Python，主代码在 `src/shuabao/`）。
- **工作分支：`claude/project-thread-fqyf7h`**，写本文时头是 `a3a509f`。所有新工作都从这个分支的最新头开始。
- main 在 `f22711e`，落后很多，不要读 main 当现状。

| PR | 分支 → 目标 | 状态 | 谁来处理 |
|---|---|---|---|
| #39 | `claude/project-thread-fqyf7h` → main | Draft，统一发布线 | 本机门禁通过、身份锚点重钉后，用 merge commit 合入 main。main 相对它只多了 #32 的 16 份文档，内容已完全包含，没有冲突 |
| #36、#37 | → 各自旧分支 / main | Open | 已被 #39 取代；#39 合入后关闭 |
| #38 | `claude/project-thread-9e94w2` → main | Draft，研究文档快照 | 独立于发布线，Owner 在 GitHub 上合 |
| #40 | `local/quicktest-20260924` → fqyf7h | Open，本地门禁失败记录 | 已审，可合；Owner 在 GitHub 上合 |
| #41 | `gpt/scheduling-research-20260924` → fqyf7h | Draft，GPT 调度量化案头调研 | 已审，可合；Owner 在 GitHub 上合 |

其它分支：
- `claude/project-thread-8rydkf`：原"单人链路兜底修复"线程的分支，开工前先合 fqyf7h，完成后 `--ff-only` 并回 fqyf7h（分叉时改用普通 merge）。新会话如果自己就在 fqyf7h 上开 topic 分支，就不再需要它。
- `integrate/runtime-core-20260919`：只作参考，不合并。

**远端分支清理：** 远端约 96 个分支，大部分已合入 main、已被 #36/#37 吸收，或属于 08-28 整合前的旧谱系；只有 15 个左右仍有独有内容。清单原本在旧 Project 的项目文件里（新会话看不到），**Owner 还没确认，一个都没删**。新会话要清理时，先用 `git branch -r --no-merged origin/claude/project-thread-fqyf7h` 等命令重新盘点，列清单给 Owner 确认后才能删。

## 3. CI 和门禁

- GitHub Actions 的 "Backend Tests & Baseline Gate" 在 #39 上稳定有 11 条失败，全部因为 CI 上没有 `.venv-ocr` OCR 运行时（OCR 模型不在仓库里）：`test_solo_main_line_close_task` ×5、`test_hitch_archive_challenge` ×3、`test_solo_fengshen_roushen` ×2、`test_attribute_bonds_whitelist` ×1。#39 上已有评论说明。**出现别的失败才需要处理。**
- 真正的门禁以 Owner 本机 Windows 为准：工作根 `G:\刷刷宝\GameScript-Local`，命令 `python tools/release_gate.py`。云端 Linux 缺 Qt 和 OCR，跑不全。
- 门禁红时会打印失败用例的 node ID，完整日志在 `logs/release_gate_<阶段>_<时间>.log`；红着时 `--update-baseline` 会被拒绝。
- **续跑规则（Owner 09-24 选定）：** 门禁红时，如果失败用例所测的代码本轮没改（判断看被测代码，不看测试文件），而且单独复跑 3 次都通过，允许再跑一次完整门禁：绿就继续，再红就停。红灯时不得刷新快照。

## 4. Owner 已定的规则（不要改）

- **"战后大厅画面"**：自己英雄打怪、打 Boss、选存档挑战 / 传家宝的那块区域，也就是常规战斗应该保持的主画面，不只是战后。
- **F2**：画面飞离战后大厅画面时（局内或战后都算），按 F2 拉回阵地。判据是小地图白色视野框偏离阵地。
- **F1**：看板丢失（看不到羁绊、技能、宝物）时按 F1。
- **木材规则**：开局先花木材点羁绊（主要战力）。木材 < 500 且技能积压时先点技能；木材 ≥ 500 且基础羁绊未成型时先点羁绊；木材 ≥ 1000 时羁绊压过技能积压。500 是初值，要实机调。
- **基础优先**：预设基础羁绊和高级羁绊出现在同一页时，先拿基础。"基础羁绊完成 80% 才推高级组"的 80% 是待实机调的值。
- **弹窗**：KK 平台 / 活动弹窗先按 Esc，关不掉再点叉。
- **上线前这些简单阈值保持不动。**

**Owner 局内规则锁：** 19 条规则登记在 `tests/test_owner_ingame_rules_lock_20260924.py` 的 `OWNER_RULES` 里，每条都指向一个行为测试；规则表在 `CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md` 的「Owner 局内规则锁」一节。Owner 最大的痛点是以前定好的局内逻辑在一轮轮架构收敛里被静默删掉。所以：**任何重构或收敛都不得删除或削弱这些锁**。改动或废止规则时，要同时改登记表，并写明 Owner 原话的日期。新定的 Owner 规则也要补锁定测试并登记。

## 5. AGENTS.md 红线（摘要，原文为准）

- 不在 main 上提交，不直接推 main；main 只经 PR 的 merge commit 前进。
- 一个 commit 只动一层：L0 大厅、L1 局内、恢复与战后、感知、外壳。
- 提交前本机过 `python tools/release_gate.py`；不改快照 `docs/baselines/GATE_BASELINE.json` 来让门禁变绿，`--update-baseline` 必须带 `--reason`。
- 改局内状态字段时同步 C2 契约的 `INGAME_POLLUTION` 清单。
- 进房 / 建房禁止颜色兜底（契约 C4）；不得用合成帧冒充真机证据。
- 看不到锚点就零输入等待（fail-closed），不要"卡住就连按 Esc"或盲点固定坐标。
- 不写入卡密、订阅信息、机器码或任何个人数据。
- 改了行为，或让某条链路的证据失效，要回写 `docs/CURRENT_STATUS_AND_HANDOFF_*.md`。

## 6. 本地实机测试现状

- 实机测试只能在 Owner 本机 Windows 上做；云端只能读代码、跑单测。
- 本地续跑提示词：`docs/handoff_20260924/LOCAL_CONTINUE_PROMPT_20260924.md`（配合 `LOCAL_QUICK_TEST_PROMPT_20260924.md`）。它基于 fqyf7h 最新头，只切测试版入口 `刷刷宝 实机测试台.lnk`，构建只用 `build_release.ps1 -NoDeploy`，正式版桌面目录不动。
- 前两轮本地门禁都在 pytest 阶段有 1 条失败后按规矩停下（记录见 #40）。第二轮定位到 `test_windows_launcher_smoke.py::test_windows_launcher_shortcut_vbs_ps1_current_and_rollback` 在全量负载下超时，单独跑 3/3 通过；`dd7d91b` 已放宽超时，待本机复核。
- **还没做、需要本机做的：**
  - 完整门禁，然后 `--update-baseline --reason "select_hero.png 资产 + 技能刷新真按钮期望纠正"`；
  - 身份锚点检查（`src/shuabao` 再有提交就要重钉，现指 `4e0b917`）；
  - 构建和冻结包 harness；
  - 入口 12 跑两局单人，19 条规则逐条给 PASS / FAIL / NOT_OBSERVED；
  - 截大圣再临、海贼王的卡族标题（两者已登记为 `pending_live_capture`）。
- 本机交接材料惯例放在 `G:\刷刷宝\handoff_prompts\`（云端看不到）。

## 7. 待 Owner 决策的两个问题（09-24 晚已答复）

答复（Owner 2026-09-24）：EX 靠合成链得到，不从面板拿；同一时刻只推进一组高级卡组，羁绊栏出现蓝色 EX（海盗为 UR）才解锁下一组，不设基础 80% 等硬门槛。实现见 `CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md` 末节。原问题保留如下：

来自 `CARD_FAMILY_PICKUP_AUDIT_20260924.md` 第二节第 3、4 条：

1. **慢卡组的 EX 终卡拿不拿？** 刀刀的解放的圣剑、修仙的大乘期、亡灵的兵主现在不拿；大圣的法天象地、异火的帝炎、封神的圣人现在拿。词典记录"获取大乘期会移除修仙卡组"、"获取解放的圣剑时移除刀刀卡组并掷骰吞噬"。
2. **同时勾选多个慢卡组时怎么换组？** 现在要持有当前组白名单 80% 的卡名才换组，可能永远凑不满，第二组就不启动。可选兜底：按时间，或按刷新次数。

## 8. GPT 协同规则

Owner 09-24 引入 GPT 协同维护仓库：
- GPT 从 fqyf7h 最新头开 `gpt/<主题>-<日期>` 分支，开 Draft PR 指向 fqyf7h；
- 不直接推 fqyf7h，不合并，不 force push，不动 main、签名或正式入口；
- 调研产出只作设计输入，不改 `src/`、`config/`、`tests/`，不动 Owner 规则锁测试；数值必须标来源等级（`live` / `guide` / `inferred` / `none`）。

GPT 的 PR 由接手的 Claude 审查，Owner 在 GitHub 上合。

## 9. Owner 的沟通偏好

- 简体中文，结论在前；代码、命令和标识保持英文。
- 不要挂太多并行待办，收敛成一条主线全盘推进；新的相关工作优先并入主线，不另开支线。
- 要提问前，先把已经授权、能做成可审查结果的部分做完。
- Owner 自称 Linus。

## 10. 下一步

按顺序：

1. 等本机续跑回传（`local/quicktest-20260924b` 的 PR 或 #40 的后续）：门禁结果、快照刷新、19 条规则核对、两局 trace。出现真实失败就抽帧固化成夹具再修。
2. 主线第二块：给刀刀、修仙、海盗、亡灵各补一条端到端拿取锁定测试（真实配置、按看板勾选方式、从首卡拿到终卡），并登记进规则锁表。**09-24 测试已补**（`tests/test_slow_pack_pickup_lock_20260924.py`），登记进规则锁表待 Owner 同意。
3. 实机截到卡顶标题后：海盗补藏宝图等成员进白名单，修仙确认练气期等卡的标题；大圣再临、海贼王补标题模板。
4. 等 Owner 回答第 7 节的两个问题后实现。
5. 主线第三块：业务进度看门狗、跨局健康统计、通知。
6. 主线第四块：三个看板的功能接入和逻辑梳理；卡组清单三份副本收成一份，并加一致性测试。
7. #39 本机门禁全绿、锚点重钉后，用 merge commit 合入 main；然后关闭 #36、#37，按 Owner 确认过的清单清理远端分支。

每完成一段就回写本文或 `CURRENT_STATUS_AND_HANDOFF_*.md`，让下一个会话从最新状态出发。

## 11. 新对话开场提示词（整段复制）

```text
接手刷刷宝项目：https://github.com/Yszdhhh/shuashuabao
工作分支 claude/project-thread-fqyf7h（统一发布线，PR #39），main 落后，不要以 main 为现状。
开工前先读：AGENTS.md → docs/handoff_20260924/PROJECT_HANDOFF_FOR_NEW_SESSION_20260924.md
→ docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md。
当前优先级：模板匹配 + 简单阈值快速上线，主线只做调度跑通、卡组拿取、长线兜底、看板接入。
Owner 规则锁 tests/test_owner_ingame_rules_lock_20260924.py 不得删改；不推 main，不删分支，不刷新门禁快照。
新改动从 fqyf7h 最新头开 topic 分支，一个 commit 只动一层；实机和完整门禁以我本机 Windows 为准。
用简体中文、结论在前回复我。读完后先告诉我你理解的现状，以及交接文档第 10 节的第一步打算怎么做。
```
