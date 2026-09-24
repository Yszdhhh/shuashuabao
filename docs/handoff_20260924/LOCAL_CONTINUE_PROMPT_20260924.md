# ShuaBao / 刷刷宝：2026-09-24 本地快速实测续跑

你是本地主 Agent，接着上一轮停下的地方继续。前两轮都在 `release_gate.py` 的 pytest 阶段遇到 1 个失败后正确地停了，没有刷新快照、构建或实跑（记录见 PR #40 和 `G:\刷刷宝\captures\local_quicktest_20260924_20260924_185305\REPORT.md`）。

第二轮定位到失败用例：`tests/test_windows_launcher_smoke.py::test_windows_launcher_shortcut_vbs_ps1_current_and_rollback`。它在门禁里失败，单独跑 3 次都通过。这个测试 09-11 之后没改过，与 main 一致，不是本轮回归。它的每一步都要冷启动 powershell/wscript，或首次运行一个刚编译的未签名 EXE（Defender 会扫描），原来的 8/12/15/20 秒上限在全量负载下不够。云端提交 `dd7d91b` 把成功路径的上限放宽到 45–60 秒：步骤跑完就立即返回，不会拖慢门禁。失败信息里现在带 rc 和耗时。

先读 `docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md` 的「本地门禁单次失败的处理（2026-09-24 晚）」一节。结论：失败只在首跑出现，最可能是 OCR 冷启动第一次推理超时，判为环境性，不是本轮回归。云端做了三件事：门禁现在会打印失败用例的 node ID 并保存完整日志；修掉了 OCR 读线程那 2 条告警；pytest 会话开始会先预热一次 OCR worker。

`docs/handoff_20260924/LOCAL_QUICK_TEST_PROMPT_20260924.md` 的第七、八、九节（证据等级、本轮不做、回传格式）继续有效。它的第二节（保护现场）上一轮已经完成，不要重做。

## 本轮边界：只切测试版入口，正式版不动

- **测试版入口**是桌面快捷方式 `刷刷宝 实机测试台.lnk`。它现在指向旧 worktree `G:\刷刷宝\Worktrees\desktop-sync-20260923\live_scenario_launcher.ps1`，固定 `-ProductionSourceSha 1b0a1a86b76db73bd91d7963743ec4cad998891c`。本轮只改这一个快捷方式。
- **正式版**包括 `C:\Users\10639\Desktop\ShuaBao`、`刷刷宝.lnk`、`current.json` 和版本目录，本轮一律不动。所以构建只用 `build_release.ps1 -NoDeploy`：它照常构建，并跑冻结包 harness，然后在部署到桌面前返回。不要跑不带 `-NoDeploy` 的构建，也不要跑 `sync_to_desktop.ps1`。
- 入口 12 从源码跑（launcher 带 `--allow-dev-source`），不依赖 EXE。所以冻结包结果只作为构建证据，不是实跑的前提。

## 第一步：换到含修复的统一分支

在默认工作根 `G:\刷刷宝\GameScript-Local` 执行：

```powershell
git rev-parse --show-toplevel
git status --short          # 必须干净；不干净就停下报告，不要清理
git fetch origin
git merge-base --is-ancestor dd7d91b origin/claude/project-thread-fqyf7h; $LASTEXITCODE
```

基点永远是 `origin/claude/project-thread-fqyf7h` 的最新头，不要写死 SHA。上面最后一条只用来确认它已包含启动器测试的修复 `dd7d91b`：返回 0 就继续；返回非 0 说明统一线程还没把修复合进来，停下报告，等它合入后再从这里开始。

```powershell
git switch local/quicktest-20260924b      # 上一轮已建好，没有新提交
git merge --ff-only origin/claude/project-thread-fqyf7h
git config core.hooksPath .githooks
```

`git merge --ff-only` 失败就停下报告，不要改用别的合并方式。

`local/quicktest-20260924` 是 PR #40 的头，保持原样，不要在它上面继续提交。

## 第二步：门禁，然后刷新快照

1. 跑 `python tools/release_gate.py`。预期只有两类快照差异：
   - `scene_templates` 资产数 404→405；
   - pytest 计数变化（`--update-baseline` 会记录新计数）。
2. 如果 pytest 或 contract 有失败，现在汇总里会逐条打出 `FAILED <node id>` 和完整日志路径。遇到失败：
   - 把每个 node 单独跑 3 次：`python -m pytest "<node id>" -q -p no:cacheprovider`；
   - 从门禁日志里把该用例的 traceback 段原样摘出来（从 `____ <用例名> ____` 到下一个分隔线），放进报告；
   - 记录 node ID、3 次结果和日志路径，然后停下报告，不要刷新快照。
   - 门禁现在会拒绝在红灯时 `--update-baseline`，这是有意的，不要绕过。
3. 只有两类预期差异、没有失败用例时，执行：

   ```powershell
   python tools/release_gate.py --update-baseline --reason "select_hero.png 资产 + 技能刷新真按钮期望纠正"
   ```

   然后把 `docs/baselines/GATE_BASELINE.json` 单独提交。
4. 再跑一次 `python tools/release_gate.py`，退出码必须为 0。

## 第三步：身份锚点检查

```powershell
python -m pytest tests/test_live_harness_refresh.py -q
```

`config/runtime_identity_manifest.json` 的 `candidate_sha` 已在云端设为 `4e0b91744ed29b25c8cb46dbdbfe74f97298e06d`，它是最后一个改动 `src/shuabao` 的提交。这条测试必须全过。

- 用 `git log -1 --format=%H -- src/shuabao` 核对。结果不是上面这个 SHA，说明 `src/shuabao` 后来又有提交：把 `candidate_sha` 改成新值，单独提交后重跑。
- 快照、文档提交不影响锚点。

## 第四步：构建（不部署）

先读 `docs/agent_shared_logs/RELEASE_HARNESS_LESSONS.md`，再执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -NoDeploy
```

核对并记录以下几项：

- 退出码；
- 脚本内置冻结包 harness 的结果；
- `dist` 下 `build_identity.json` 的 `source_sha` 等于 `git rev-parse HEAD`；
- `exe_sha256`。

最后确认桌面 `ShuaBao\build_identity.json` 和 `刷刷宝.lnk` 的修改时间没有变，也就是正式版确实没动。构建失败就报 `FAIL/BLOCKED` 并停下，不影响下一步能否实跑的判断。遇到这种情况先报告，由云端决定。

## 第五步：切测试版入口

1. 把现在的 `刷刷宝 实机测试台.lnk` 复制一份到 `G:\刷刷宝\handoff_prompts\backup_20260924_20260924_175833\`，便于回退。
2. 把它改成指向 `G:\刷刷宝\GameScript-Local\live_scenario_launcher.ps1`，参数为：

   ```
   -ProductionSourceRoot "G:\刷刷宝\GameScript-Local" -ProductionSourceSha <git rev-parse HEAD 的完整 40 位>
   ```

   工作目录设为 `G:\刷刷宝\GameScript-Local`。
3. `-ProductionSourceSha` 必须等于当前 HEAD，否则 READY FOR GT 会是 NO。之后若再有提交（比如回写报告），实跑前要同步更新这个参数。回写报告最好放到实跑之后。
4. 用入口 **1（启动前检查）** 确认 `READY FOR GT: YES`，`Production candidate SHA` 就是这个 HEAD。

## 第六步：入口 12 跑两局单人，核对 19 条规则

按 `LOCAL_QUICK_TEST_PROMPT_20260924.md` 第六节执行：

- 跑 2 局，每局保留 trace 和 capture bundle；
- 出现 TIMEOUT、CANCELLED 或循环点击时抽帧固化成夹具，不在现场修代码；
- 19 条 Owner 规则逐条给出 PASS / FAIL / NOT_OBSERVED，并附 trace 行号或截图；
- 记录几次实际木材值和调度理由，给 500 这个阈值用；
- 截取大圣再临、海贼王的卡族标题。

## 第七步：B 类研究文档

上一轮列出的 10 份 B 类文档，统一分支里都有同名文件。唯一例外是 `COMPETITOR_STATIC_OBSERVATIONS_1_6_3`：统一分支里它叫 `docs/research/COMPETITOR_STATIC_OBSERVATIONS_1_6_3_20260923.md`（来自 #34），本地 wip 里的是 `_20260922` 版。

对这 10 份，用 `git diff --no-index <wip 版> <统一分支版>` 各比一次：

- 统一分支版覆盖了 wip 版：不补，报告里写"已覆盖"。
- wip 版有统一分支没有的内容：从 `origin/main` 新开 `docs/local-research-20260924`，只提交这些文件，推上去报告分支名。云端会把它并进研究文档 PR #38，不进发布线 #39。

不要整体推送 `wip/local-dirty-20260924`。

## 回传

按 `LOCAL_QUICK_TEST_PROMPT_20260924.md` 第九节的格式回传，另外加三项：

- 门禁失败时的 node ID 和日志路径；没失败就写"无"；
- 测试版快捷方式的修改前后目标，以及备份路径；
- 正式版未改动的证据：修改时间或 hash。

把新分支 `local/quicktest-20260924b` 推上去，开一个指向 `claude/project-thread-fqyf7h` 的 PR，与 #40 做法相同。

结果回写到 `docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md` 末尾，接在 #40 那节后面：写明源码 commit、构建产物 hash（`-NoDeploy`，未部署）、测试版入口，以及仍需真机验证的项目。

**禁止**：

- `git reset --hard`、`git clean -fd`、`git checkout .`、`git restore .`；
- 强制 pull、force push；
- squash/rebase 合并、自动 merge；
- 改 main；
- 改正式版桌面或 `刷刷宝.lnk`；
- 动签名、订阅、manifest、授权链。
