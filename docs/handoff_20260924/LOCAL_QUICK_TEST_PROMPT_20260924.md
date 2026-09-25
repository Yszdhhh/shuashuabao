# ShuaBao / 刷刷宝：2026-09-24 统一分支（PR #39）本地快速实测任务

你是本地主 Agent，接手 ShuaBao 这一轮的本地实测。这份提示词**取代** 2026-09-23 那份「三路成果云端整合后本地同步与实施任务」。那份里以下内容已经过时，不要再照做：

- 以 `integrate/cloud-convergence-20260923` / `d5d7107` 为基点建 worktree；
- 「PR #34 保持 Draft」和 PR #32/#33/#34 的处置；
- W0–W5 的大实施计划。它们推迟到下一轮，本轮不做。

那份里仍然有效、本轮继续遵守的部分，见第二节和第六节。

本轮只做一件事：**把统一分支在本机刷新门禁、构建、跑一轮单人短测，并按清单核对 Owner 局内规则。**不做重构，不新增功能，不做提速。

---

## 一、现在的权威代码在哪里

- 仓库：https://github.com/Yszdhhh/shuashuabao
- 权威分支：`claude/project-thread-fqyf7h`，即 Draft PR #39「integrate: unify #37 and #36 into one release line」，base 是 `main`（`f22711e`）。
- 分支头必须包含提交 `8a0266d`（Owner 局内规则锁），以及它之后的交接文档提交。`git fetch` 后用 `git merge-base --is-ancestor 8a0266d origin/claude/project-thread-fqyf7h` 确认，返回非 0 就停下来报告。
- #39 已经吸收：#36、#37 全部提交；#34 的 12 个提交（统一线程逐行核对过）；09-24 单人链路修正（三条 Owner 决策、回归修复、F2 返回阵地、平台弹窗先 Esc 再点叉、Owner 局内规则锁）。
- 唯一的现状文档：`docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md`。先读它，再读 `AGENTS.md` 和 `docs/agent_shared_logs/RELEASE_HARNESS_LESSONS.md`（构建前必读）。

### 来源说明（沿用 09-23，别混淆）

09-23 有三条独立工作流，由**三个不同的 Agent** 各自执行、各自产出：

1. 整体架构与生产代码整理（PR #33）；
2. 游戏机制深度交叉调研（PR #32）；
3. 竞品深度拆解（文档也落进了 PR #32）。

第 2、3 条只是 Git 落点重合，不是同一个 Agent 的工作。它们都属于研究和证据输入，不是生产授权。本轮不重新调研，也不照搬研究里的数字（440、999、固定 300 秒、固定 ESC、固定 Boss 网格等）。

---

## 二、第一步：保护本地现场（不可跳过）

在默认工作根 `G:\刷刷宝\GameScript-Local` 里执行下面四条命令，把输出存到 `G:\刷刷宝\handoff_prompts\backup_20260924_<时间>\state.txt`：

```powershell
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse HEAD
git log -n 10 --oneline
```

同一目录再存 `git diff > worktree.patch`、`git diff --cached > staged.patch`，并把未跟踪文件清单连同文件本身复制过去。

**禁止**：`git reset --hard`、`git clean -fd`、`git checkout .`、`git restore .`、强制 pull、force push、在脏工作树上直接切分支或合并。

工作树不干净时，先把未提交内容分类：

- A. 已被 #39 覆盖
- B. 云端没有的有效新增
- C. 临时调试
- D. 备份
- E. 生成文件
- F. 疑似冲突实现

然后执行 `git switch -c wip/local-dirty-20260924`，把所有内容原样提交到这个分支（`git add -A && git commit`）。B 类不能丢，在报告里逐条列出来，留到下一轮处理。

`config/choice_lexicon.json` 要单独确认：它必须存在，且与 #39 里的版本一致。09-23 它曾被误删，后来从备份恢复过。

## 三、第二步：切到统一分支

```powershell
git fetch origin
git switch -c local/quicktest-20260924 origin/claude/project-thread-fqyf7h
git config core.hooksPath .githooks
```

必须在默认工作根里做，不要在 sibling worktree 或桌面副本里交付（AGENTS.md 第 6 节）。

## 四、第三步：门禁与身份锚点

1. `python tools/release_gate.py`。云端预期有两类有意的快照差异：
   - `scene_templates` 的资产数从 404 变为 405，原因是新增了 `assets/Images/select_hero.png`；
   - 冻结回放 `giveup_panel_not_fail` 的点击点改成了真正的【刷新(3)】(1171,677)。

   pytest 阶段在本机应该全绿，因为本机有 `.venv-ocr` 和 Qt。除这两类差异外还有任何失败：**不要更新快照**，原样记录命令、退出码和失败名单，然后停下报告。
2. 只有上面两类差异时，才执行：
   `python tools/release_gate.py --update-baseline --reason "select_hero.png 资产 + 技能刷新真按钮期望纠正"`，然后把 `docs/baselines/GATE_BASELINE.json` 单独提交。
3. 身份锚点：云端已把 `config/runtime_identity_manifest.json` 的 `candidate_sha` 设为 `8a0266d` 的完整 SHA，它是最后一个改动 `src/shuabao` 的提交。锚点只比较 `src/shuabao`，快照、文档、配置提交都不影响它。先跑 `python -m pytest tests/test_live_harness_refresh.py -q`：
   - 全过就不用动；
   - 如果 `src/shuabao` 在 `8a0266d` 之后又有新提交，就把 `candidate_sha` 改成最后一个改动 `src/shuabao` 的提交（完整 40 位），单独提交后重跑，必须全过。
4. 再跑一次 `python tools/release_gate.py`，退出码必须为 0。

## 五、第四步：构建与桌面落地

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

构建后核对以下几项，任一项不一致就停止交付，报 `FAIL/BLOCKED`：

- `C:\Users\10639\Desktop\ShuaBao\build_identity.json` 的 `source_sha` 等于 `git rev-parse HEAD`；
- `刷刷宝.lnk` 指向该目录；
- 脚本内置的冻结包 harness 两次都通过。

需要 UAC 或真实游戏交互才能启动 EXE 时，状态只能写 `BLOCKED`，不能用 pytest 代替。

## 六、第五步：单人短测与规则核对

入口：`live_scenario_launcher.ps1` 的 **12 号（单人完整循环）**。它读取正式看板的 `user_settings.json`，也需要 READY FOR GT = YES，所以要先完成第四步的身份锚点。

先跑 2 局，关卡用看板当前配置。每局保留 trace 和 capture bundle。出现 TIMEOUT、CANCELLED 或循环点击时，按 AGENTS.md 抽帧固化成夹具，不要当场改代码。

### 核对清单

`docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md`「Owner 局内规则锁」一节有 19 条规则。实测时逐条给出三种结论之一，每条附 trace 行号或截图：

- **PASS**：实际观察到规则生效；
- **FAIL**：观察到违反规则的动作；
- **NOT_OBSERVED**：本局没有出现触发条件。

重点核对这几条：

1. 「点击进化」金条亮着时，物品栏 2–6 格一次都没被点；进化选完英雄后才用英雄卡或逐格试用（规则 1、2、16）。
2. 误点小怪、看板丢失后按的是 F1，不是 F2（规则 3）。
3. 画面飞走时按 F2 回阵地（规则 4）。trace 里会出现「战斗主画面阵地已学习」和「按 F2 返回阵地」。画面没飞走就记 NOT_OBSERVED。可以手动拖动一次镜头来触发，但结论里必须注明是人为触发。
4. 木材 < 500 且有技能积压时先点技能；木材 ≥ 500 且基础羁绊没成型时先点羁绊（规则 5、6、7）。记下几次实际的木材值和调度理由，给 Owner 调 500 这个阈值用。
5. 同一页有预设基础羁绊和高级羁绊时拿的是基础（规则 8）。
6. 宝物角标有数时，V 在它那一步能打开（规则 9）。
7. 技能面板点的是【刷新(N)】，没有点到【放弃】（规则 11）。
8. 负面宝物一张都没拿（规则 13）。
9. 羁绊选卡面板出现「大圣再临」或「海贼王」卡时，截图卡顶那行卡族名。这两个卡族在 `templates_index.json` 的 `pending_live_capture` 里等补图，截图交给云端切模板。

单人短测通过后，如果还有时间，可以用 13 号入口跑夜间蹭车长测。这是可选项，单人短测没过就不要跑。

## 七、证据等级（沿用 09-23，严格区分）

依次为：Synthetic unit < Offline replay < Recorded live frame < Live observation < Live action < Business postcondition < Frozen package validation < Production desktop validation。

- 点击成功不等于业务成功，画面变化不等于 Boss、商店或服务真的执行成功。
- 合成帧不能当实机证据（AGENTS.md 第 4 条）。
- 门禁没有给出结论（超时、卡住、Qt 偶发失败）时，照实写，不能写成 PASS。

## 八、本轮不做

- 提速重构（分级识别 L1/L2/L3、`recognition_profile`）、W1–W5、solo shadow 接管，都留到下一轮。
- 不合并任何 PR，不改 main，不 force push，不 squash 或 rebase 合并，不自动 merge。
- 签名、订阅、manifest、授权链不动。
- 实测中发现的代码问题只抽帧固化成夹具并报告，**不在本轮现场修**。修复交回云端统一分支，叠在 #39 上。

## 九、回传格式

结束时回传：

- 起始分支/SHA、最终分支/SHA、新增提交列表；
- 每条命令原文、退出码、结果；
- 门禁快照更新的原因与 diff 摘要；
- 构建产物 hash 与 `build_identity.json`；
- 单人短测局数、结果、trace 路径；
- 19 条规则逐条的 PASS/FAIL/NOT_OBSERVED 及证据；
- 大圣再临/海贼王截图路径；
- `wip/local-dirty-20260924` 里 B 类内容清单；
- 需要 Owner 拍板的事项。

最后把结果回写到 `docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md`：写明本次源码 commit、产物 hash、正式入口，以及仍需真机验证的项目（AGENTS.md「会话结束前」）。
