# ShuaBao / 刷刷宝：本地第四轮实测（Owner 09-24 新规则上机）

你是本地主 Agent。云端已把 Owner 2026-09-24 的新规则并入 `claude/project-thread-fqyf7h`：
基础羁绊顺序、高级卡组单组推进到 EX、单人默认吃吞噬丹（≥6/10，亡灵进行中不吃）、
羁绊栏过半没丹/木材 < 500 插队去黑商、木材三档 500/1000、羁绊栏 EX 模板 11 张。
这一轮的目标只有一个：**用源码入口 12 跑两局单人，按调度链路逐条核对，拿回 trace 和素材。**

开工前先读：
1. `AGENTS.md`（注意新增 §1.1 纯资料快速通道）；
2. `docs/handoff_20260924/SOLO_SCHEDULING_CHAIN_20260924.md`：本轮核对的依据，每条都有 trace 关键字；
3. `docs/CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md` 的「Owner 局内规则锁」表（现在 28 条）和末节。

## 第零步：保护工作根

上一轮默认工作根被另一个会话切到了别的分支，导致入口 1 读到错误 SHA。开工前：

```powershell
git rev-parse --show-toplevel          # 必须是 G:\刷刷宝\GameScript-Local
git status --short                     # 必须为空；不空就停下报告，不清理
git worktree list
```

本轮期间，任何别的会话（交资料、做研究）都只能在自己的 worktree 里工作，不得在默认工作根切分支。
你自己要交素材时也按第六步用单独的 worktree。

## 第一步：从 fqyf7h 最新头开新分支

```powershell
git fetch origin
git switch -c local/quicktest-20260924c origin/claude/project-thread-fqyf7h
git config core.hooksPath .githooks
git log -1 --format=%H -- src/shuabao   # 应为 5a23ce4c742e5ebb601e7a610697e2e6975726e1
```

`local/quicktest-20260924b`（含上一轮的快照提交 `88eb4d2`）保留不动、不推送；这一轮会重新刷新快照。

## 第二步：门禁，然后刷新快照

1. `python tools/release_gate.py`。预期只有这些快照差异：
   - `scene_templates` 资产数 404 → 416（`select_hero.png` + `assets/Images/bond_bar/` 11 张 EX 模板）；
   - pytest、contract 的通过数（新增了规则锁和调度测试）。
2. 有失败用例时按原规则处理：每个 node 单独跑 3 次，摘出门禁日志里的 traceback；
   被测源码本轮没改且 3/3 通过，允许重跑一次完整门禁；重跑再红就停下报告。红灯时不刷新快照。
3. 门禁只剩上面的预期差异时：

   ```powershell
   python tools/release_gate.py --update-baseline --reason "select_hero.png + EX 羁绊栏模板 11 张 + Owner 09-24 拿卡与紧急资源规则测试"
   ```

   把 `docs/baselines/GATE_BASELINE.json` 单独提交，再跑一次门禁，退出码必须为 0。
4. `python -m pytest tests/test_live_harness_refresh.py -q` 必须全过（锚点 `5a23ce4`）。

**本轮不构建冻结包**：冻结构建需要操作员 Ed25519 私钥，Owner 没提供前一律不找、不配，报告里写"未构建（缺操作员私钥）"。

## 第三步：测试台入口

测试台快捷方式现在指向 `G:\刷刷宝\GameScript-Local\live_scenario_launcher.ps1`，参数里的 SHA 还是上一轮的 `88eb4d2`。
只把 `-ProductionSourceSha` 改成当前 `git rev-parse HEAD` 的完整 40 位（快照提交之后的 HEAD），其它不动。
用入口 **1** 确认 `READY FOR GT: YES`。不是 YES 就停下，原样报告那一行原因，不改 launcher 或 manifest。

## 第四步：入口 12 跑两局单人

- 局 1：沿用看板当前配置。
- 局 2：如果 Owner 同意，在看板加勾「亡灵」卡组（用来观察规则 27）；Owner 没同意就沿用配置，规则 27 记 NOT_OBSERVED。

每局保留 trace 和 capture bundle。出现 TIMEOUT、CANCELLED、循环点击时抽帧固化，**不在现场改代码**。
实机 UI helper 报 `SetIsBorderRequired` 时不要用它截图，改用产品 capture bundle 里的帧。

### 核对清单（按 `SOLO_SCHEDULING_CHAIN_20260924.md` 的顺序）

28 条规则逐条给 PASS / FAIL / NOT_OBSERVED，并附 trace 行号或帧。重点：

1. **木材三档**：记录至少 5 次木材读数和当时的决定（trace：`木材 N < 500 且技能积压`、`木材充足`、`基础羁绊未成型，羁绊优先`）。
2. **插队黑商**：统计每 10 分钟插队几次（`插队去黑商`），黑商是否开出来（`按 [H] 打开黑商…`），买到了什么；
   插队后下一步是否回到被打断的那一步；技能和宝物有没有因为插队被饿死。
3. **吞噬丹**：羁绊栏到 6/10 时是否点了丹（`UseInventory-swallow_pill`），点完羁绊格数是否变少；
   **录一次完整事务**：点丹前逐格截羁绊栏 → 点丹 → 是否弹出"选吞哪张" → 哪张消失。
   亡灵进行中是否完全没吃丹。
4. **拿卡顺序**：同页基础卡和高级卡时拿的是基础（`基础羁绊优先`）；基础之间的先后是否是 祝福 → 成长 → 经济 → 挑战 → 力量 → 智力 → 敏捷 → 其他。
5. **高级卡组**：只推进一组（`当前高级卡组持续推进`）；如果某组合成出 EX，trace 应出现 `羁绊栏出现第 N 张 EX，解锁下一组高级卡组`。
   出现 EX 但没有这行，就是模板没认出：截那一帧。
6. F1（看板丢失）、F2（`按 F2 返回阵地`）、平台弹窗 Esc→叉 照旧核对。

## 第五步：要截的素材

- 羁绊栏里真实出现的 EX 卡：整屏帧 + 鼠标悬停详情帧（校准 `assets/Images/bond_bar/`）；
- 吞噬丹完整事务（上面第 3 条）；
- 单人按 H 打开黑商：有丹、有木材礼包、杀敌数不够各 1 帧；
- 物品栏 2–6 满格时每格的 tooltip；单人按 B 打开背包：空、半满、满各 1 帧。

## 第六步：素材走快速通道（不跑门禁）

```powershell
git worktree add "G:\刷刷宝\Worktrees\material-live-20260924" -b material/live-captures-20260924 origin/claude/project-thread-fqyf7h
# 素材复制到该 worktree 的 fixtures/live_captures/20260924/，附一份 README.md 说明每张图是什么
git -C "G:\刷刷宝\Worktrees\material-live-20260924" add fixtures/live_captures/20260924
python "G:\刷刷宝\Worktrees\material-live-20260924\tools\check_material_commit.py"   # 在该 worktree 目录里运行，退出码 0 才提交
```

提交、推送 `material/live-captures-20260924`，开 PR 指向 `claude/project-thread-fqyf7h`。不跑 pytest。

## 回传

- 起止分支与 SHA、新增提交；门禁首跑/重跑结果与失败 node；快照刷新的 reason 与 diff 摘要；
- 入口 1 的 READY FOR GT 行；两局结果、trace 与 bundle 路径；
- 28 条规则的 PASS / FAIL / NOT_OBSERVED 表（附证据）；
- 木材读数与决定、插队黑商次数与结果、吞噬丹事务、EX 识别情况；
- 素材 PR 链接；
- 需要 Owner 拍板的事项。

推送 `local/quicktest-20260924c`，开 PR 指向 `claude/project-thread-fqyf7h`；结果回写 `CURRENT_STATUS_AND_HANDOFF_20260924_UNIFIED.md` 末尾。

**禁止**：`git reset --hard`、`git clean -fd`、`git checkout .`、`git restore .`；force push；改 main；
改正式版桌面、`刷刷宝.lnk`、`current.json`；动签名、订阅、manifest、授权链；在默认工作根切到别的分支做别的事。
