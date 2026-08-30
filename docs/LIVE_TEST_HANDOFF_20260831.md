# Live 实机测试交接（2026-08-31）

## 1. 当前基线

- 实际实机 worktree：`G:\刷刷宝\Worktrees\live-test-boss-05ed271`
- 当前提交：`2bbc709f99cb52824a5600f7927549b5589a8490`
- 桌面入口：`C:\Users\10639\Desktop\刷刷宝 Live 实机测试.lnk`
- 桌面入口实际调用：`G:\刷刷宝\Worktrees\live-test-boss-05ed271\live_scenario_launcher.ps1`
- Live EXE：`G:\刷刷宝\Worktrees\live-test-boss-05ed271\dist\ShuaBao\ShuaBao.exe`
- Capture 输出：通常为 `C:\Users\10639\AppData\Local\Temp\shuabao-captures`
- 当前 EXE 的 `build_identity.json` 与源码 SHA、实际 EXE SHA 已核对一致。

桌面快捷方式使用的是 worktree，不是 `G:\刷刷宝\GameScript-Local` 主目录。两处启动器文字或菜单如果不一致，以桌面快捷方式指向的 worktree 为准。

本轮没有重构 `Mediator`，没有复制生产识别/FSM，没有新增 watchdog、retry、recovery 或 fallback。Live Capture 仍通过现有 `tools/live_scenario_capture.py`，Replay 仍通过现有 `ReplayCaseLoader / FakeClock / FakeInputExecutor`。

## 2. 当前启动器菜单

`live_scenario_launcher.ps1` 只负责路径发现和参数转发：

| 菜单 | 当前行为 | 生产输入 |
|---|---|---|
| 1 | readiness/preflight 能力检查 | 否 |
| 2 | inventory_item：背包吞噬丹/英雄卡局部探针 | 是，现有 inventory handler |
| 3 | black_merchant + 背包/神器长探针，最长 600 秒 | 是，现有 merchant/inventory/artifact handler |
| 4 | boss_challenge：tqtz → Boss → 结算 → 存档 8 项 → 传家宝配置 Boss | 是，现有 `Mediator.tick()` |
| 5 | secret_realm：从胜利后 NPC/确认页请求进入并验证 HUD | 是，现有秘境 handler |
| 6 | time_cave Ground Truth | 否，zero-input |
| 7 | heirloom：自动找/滚动/点击 `cjb_boss` 并等真实 HUD | 是，现有 `_maybe_challenge_configured_boss` |
| 8 | 打开最新 FAIL/BLOCKED bundle | 否 |
| 9 | reproduce 最新 FAIL bundle | 否，进入现有 Frozen Replay |

启动实机前仍必须满足：1600×900、只运行一份 Live Capture、不要同时启动普通 `ShuaBao.exe`，游戏窗口标题/尺寸可识别，OCR bootstrap healthy，源码/EXE identity 一致。preflight 不通过时为 `BLOCKED_PRECHECK`，不进入业务 handler、不发游戏输入。

## 3. Readiness 与真实生产状态

`readiness --quick` 在当前提交输出六个 target 均 `HARNESS READY`，但生产状态不是全部 READY：

| Target | HARNESS_READINESS | PRODUCTION_READINESS | 当前含义 |
|---|---|---|---|
| `black_merchant` | READY | CONDITIONAL | 可测刷新、吞噬丹/木材/2折5折和背包链；真实商品仍需实机确认 |
| `inventory_item` | READY | CONDITIONAL | 可测吞噬丹、英雄卡；悬赏令只有 Ground Truth |
| `boss_challenge` | READY | CONDITIONAL | 可测 tqtz/Boss/结算/存档 8 项/传家宝配置 Boss；秘境隔离 |
| `time_cave` | READY | BLOCKED | 战后时光之穴 NPC 生产入口未接线，只采人工 Ground Truth |
| `heirloom` | READY | CONDITIONAL | 现有 `cjb_boss` 选择、滚动和真实 HUD 后置可实测 |
| `secret_realm` | READY | CONDITIONAL | 只能从 NPC/确认页走现有 Open/Confirm，必须真实 HUD + `_secret_realm_active` |

`HARNESS READY` 只代表 capture、bookmark、failure summary、replay conversion 能运行，不代表生产功能已经接线或已经实机 PASS。

## 4. 已完成的关键修复

### 黑商

- `9e20740`：从整条商品条逐像素 fingerprint 改为五槽占用 + 已识别目标，避免商品动画导致永远无法进入 READY。
- `ac1319e`：没有 2折/5折/吞噬丹/木材时刷新，刷新后清理 purchases。
- `7bfd423`：刷新点改为 `(0.911, 0.702)`；黑商在场时允许现有背包吞噬丹 handler；回收钮消失才停。
- `c180a8b`：`merchant_max_rerolls=0` 表示不设脚本上限，内部安全顶为 20。
- `fdc4821`：刷新后指纹不变回 READY；只有购买后验证失败才进入 EVICTED。
- `41e4681`：商品匹配改为最近固定槽位，使用稳定槽中心点击；补充已观察到的 `15折→5折`、`A2→2折`、`12折→2折` OCR 别名；未知 `2S` 仍拒绝购买。

### Boss/传家宝

- `d81a7ca`：加入较低 Boss 列表的滚动测试覆盖。
- `0029159`：改用正确的瑞文戴尔男爵素材。
- `3ccb1d3` / `6300bda`：允许从已打开存档列表或战后 Hub 接手。
- `21dc0ae`：收紧战后 Boss 证据和匹配。
- `85f9a2f` 至 `981d974`：把战后存档 8 项和传家宝流程纳入现有生产链，识别已挑战面板并在完成后前进。
- `a8fb21a`：增加传家宝挑战结果后置确认。
- `1aabb6a`：等待配置 Boss 的真实胜利状态后再退出。
- `2bbc709`：传家宝结果判定增加红色连通区域条件，避免半透明弹窗后的战斗红色特效被误判为“已挑战”，导致未点击/未打完就关闭窗口。

## 5. 多轮真实 bundle 结论

所有路径均为本机 `C:\Users\10639\AppData\Local\Temp\shuabao-captures` 下的原始 bundle；bundle 内有 manifest、关键帧、trace、输入结果和 replay 转换信息。

### 黑商历史

| Bundle | 当时 SHA | 现场现象 | 结论/处理 |
|---|---|---|---|
| `black_merchant_20260830_010555_176097` | `4a0eb79` | 第三槽吞噬丹模板命中约 0.981，但商品条逐像素变化，actions 为空，最终 timeout | fingerprint 过细；已由 `9e20740` 修复 |
| `black_merchant_20260830_014111_091497` | `9e20740` | 第三槽吞噬丹成功拿到，`LIVE_PROBE_PASS` | 证明吞噬丹主链可以成功；当时 reroll=0 仍受旧上限影响 |
| `black_merchant_20260830_015744_427554` | `ac1319e` | 有 refresh 日志但商品不变 | 刷新点落在回收钮右侧草地；已由 `7bfd423` 修复 |
| `black_merchant_20260830_023440_018574` | `7bfd423` | 吞噬丹拿到并使用，木材拿到；刷新 3 次后停止 | `can_reroll(3)` 写死；已由 `c180a8b` 修复 |
| `black_merchant_20260830_024611_475051` | `c180a8b` | 刷到第 4 次，木箱模板误认成 `BlackMerchant-wood`；占用 fingerprint 不变后 EVICTED | 需要继续观察 merchant_wood 模板误匹配；刷新不变回 READY 已由 `fdc4821` 修复 |
| `black_merchant_20260830_233034_305060` | `1aabb6a` | 背包吞噬丹被拿到并使用，自动后置确认 | 该 bundle 是最新一条吞噬丹成功证据，但早于折扣/槽位修复 |

后续实机反馈又发现两类风险：有时 2折道具被略过，有时拿了正价道具或木材相邻格。代码已在 `41e4681` 修复槽位映射和已观察 OCR 别名，但修复后的真实折扣/木材样本还需要重新采集，不能只靠离线测试宣布完全解决。

另有边界：

- 8折、宝石、杂物不买；不是缺陷。
- 黑商购买吞噬丹不检查羁绊；背包使用吞噬丹仍走羁绊和 `WAIT_DEVOUR_DAN` 后置。
- 英雄卡应打开真实英雄选择页，不应“拿到后直接吞掉”；尚缺新的实机确认样本。
- 海盗悬赏令有 N/R/SR/SSR/UR 五种颜色，是消除海盗卡组的道具；当前没有生产模板和后置验证，只采 Ground Truth。

### Boss/存档/传家宝历史

从 `boss_challenge_20260830_135632_119010` 到 `boss_challenge_20260831_001844_095557` 的多轮 bundle 主要推动了：接手已打开页面、滚动低位 Boss、存档 8 项顺序、传家宝进入和战后退出保护。

关键样本：

- `boss_challenge_20260830_225114_627630`：在 `PREPARE` 阶段 capture 无有效帧，记录为 BLOCKED；没有业务归因。
- `boss_challenge_20260831_001844_095557`：8 个存档挑战均实际点击成功，之后打开传家宝页，但没有点击配置的 `08战争雷霆蜥蜴`，随后错误关闭窗口并走到错误主线动作。根因是半透明窗口后面的战斗红色特效被 `_heirloom_boss_result_visible()` 误判为结果 toast。
- `heirloom_20260831_005452_972761`：使用 `2bbc709` 启动，preflight READY，但只有 1 帧、没有 authoritative result，不能作为传家宝成功证据；需要新的真实运行验证修复后的点击和等待链。

当前最重要的实机验收仍是：传家宝列表中配置 Boss 可被命中（必要时滚动），点击后脚本持续等待真实挑战 HUD/胜利后置，不提前关闭；之后再单独验证秘境。

### 当前尚未完成的链

1. **时光之穴战后 NPC → 时光之穴**：生产入口仍 BLOCKED；只能用菜单 6 人工完成并采集 Ground Truth，不能把它标为生产 PASS。
2. **传家宝最新修复后的真实 PASS**：代码和回归测试已通过，但 `2bbc709` 后还没有完整实机 PASS bundle。
3. **Boss → 传家宝 → 秘境的 Natural E2E**：Boss capture 会隔离 `auto_secret_realm`，秘境用菜单 5 单独测；完整自然链仍未取得一次无人工介入的真实 PASS。
4. **秘境后置**：只有真实局内 HUD 且 `_secret_realm_active=True` 才算 PASS；打开 NPC 或点击确认不算。
5. **装备栏全道具**：吞噬丹已有成功证据；英雄卡真实选择页、神器多槽位、悬赏令仍需分别采样。
6. **长线程稳定性**：黑商 600 秒长探针、刷新次数耗尽、连续杀敌后再用背包物品仍需在当前 SHA 做回归；不能用一次短 probe 代替。

## 6. 失败归因顺序

不要看到“没点”就直接改坐标。先按 bundle 的证据分类：

1. `BLOCKED_PRECHECK`：先处理源码 SHA/EXE identity、OCR bootstrap、窗口 HWND/title/size、single-instance；不作业务归因。
2. 有画面且目标可见但 detector 没命中：`L1/L2`，看 template score、OCR raw/normalized/candidate、ROI 和滚动后的帧。
3. detector 命中、policy 正确但没有 input：`L4_INPUT_EXECUTION`。
4. input 发出但 frame 不变：优先 `L4/L5`，检查点击坐标、窗口缩放、实际输入结果和前后指纹。
5. frame 已变化但 FSM 不推进：`L6_FSM_TRANSITION`。
6. 本轮成功、下一轮残留旧状态：`L7_LIVENESS_RESET`。
7. 缺帧、bookmark 或 summary 不完整：`L0_CAPTURE_ENV/L8_TEST_EVIDENCE`。

允许 `UNKNOWN` 或多个候选；不允许没有证据的单点猜测。

## 7. 实机操作约定

- 启动前关闭普通 `ShuaBao.exe`，确保游戏为 1600×900，取消游戏暂停。
- 到达目标页面后启动对应菜单，启动后放开鼠标。
- `p/f/m` 是 PASS/FAIL/MANUAL_INTERVENTION 证据 bookmark，不是暂停键。
- 当前没有普通“暂停/恢复模块”功能。切换模块时按 `F12` 或 `Shift+F12` 安全结束当前采集，等菜单回来后再启动下一个目标。
- `m` 只适合在自动失败后人工绕过并继续采集；使用过 `MANUAL_INTERVENTION` 的链路不能计为 Natural E2E PASS。
- `4` 测 Boss/存档/传家宝配置 Boss；`6` 时光之穴只做人工 Ground Truth；`7` 是传家宝生产实测；`5` 是秘境生产实测。

## 8. 离线验证记录

- 传家宝红色特效回归：`33 passed, 2 subtests passed`。
- 当前 `readiness --quick`：六个 target `HARNESS READY`；生产状态按第 3 节分别为 CONDITIONAL/BLOCKED。
- Frozen replay：既有 6 个场景 PASS，`disconnect_modal_missing` 仍是既有 BLOCKED 项。
- 本次完整 `release_gate.py` 未在 worktree 的 `.venv` 中执行成功，因为该环境没有安装 `pytest`，不是本次代码断言失败。用主仓库 `.venv` 直接跑全量时存在其它环境/历史测试失败，不能把它伪报为绿色；接手者应先恢复正确 dev interpreter，再按仓库 gate 重跑。

## 9. 给下一位 Agent 的背景交接词

```text
你接手的是 G:\刷刷宝\Worktrees\live-test-boss-05ed271，不是主目录的旧副本。
当前基线是 commit 2bbc709f99cb52824a5600f7927549b5589a8490，桌面快捷方式
C:\Users\10639\Desktop\刷刷宝 Live 实机测试.lnk 指向该 worktree 的
live_scenario_launcher.ps1。不要同时启动普通 ShuaBao.exe；Live EXE 是
dist\ShuaBao\ShuaBao.exe，启动任何 live-input 前必须通过现有 preflight，核对
源码 SHA、EXE build_identity/实际 hash、settings snapshot、OCR bootstrap、游戏
HWND/title/1600x900 和 single-instance。

原任务不是继续扩展测试框架，而是把真实问题沉淀为 capture bundle → 现有
ReplayCaseLoader/FakeClock/FakeInputExecutor。禁止复制生产业务/识别/FSM，禁止
新增 watchdog/retry/recovery/fallback，禁止为了测试把 BLOCKED target 改成 READY。

当前 target 事实：black_merchant CONDITIONAL，inventory_item CONDITIONAL，
boss_challenge CONDITIONAL，heirloom CONDITIONAL，secret_realm CONDITIONAL；
time_cave 的战后 NPC 入口仍 BLOCKED，只做 Ground Truth zero-input。桌面菜单 4
跑 tqtz→Boss→结算→存档 8 项→传家宝配置 Boss；菜单 5 从胜利后 NPC/确认页
实测秘境并要求真实 HUD + _secret_realm_active；菜单 6 只取时光之穴人工证据；
菜单 7 才是传家宝生产 handler 实测。

黑商历史根因和修复已在 docs/LIVE_TEST_HANDOFF_20260831.md：曾有商品条逐像素
fingerprint、刷新点错、reroll 写死 3、刷新不变误 EVICTED、槽位相邻误点和
折扣 OCR 别名问题。当前 41e4681 已修复槽位映射/稳定点击和已观察折扣别名，
但要用当前 SHA 重新采真实 2折/5折、木材、吞噬丹样本。英雄卡真实英雄选择页、
海盗悬赏令、神器多槽位仍需实机样本。

Boss 历史最近的关键失败 bundle 是
C:\Users\10639\AppData\Local\Temp\shuabao-captures\boss_challenge_20260831_001844_095557：
存档 8 项点击成功，但传家宝 Boss 未点，原因是半透明窗口后的战斗红色特效被
误判为传家宝结果 toast。2bbc709 已增加红色连通区域判定；测试 33 passed +
2 subtests，EXE 也已重建，但 2bbc709 后还没有完整真实 PASS，接下来应直接实机
验证：传家宝配置 Boss（必要时滚动）→点击→等待真实挑战 HUD/胜利，不提前关闭。

实机失败先保 bundle，不要现场连续打补丁：看 preflight、最后 anchor、ROI/template/OCR、
policy、实际 input、前后 frame fingerprint、phase/FSM 和 postcondition，再按 L0-L8
分类，之后离线 replay。p/f/m 只做证据标记；m 会取消 Natural E2E 资格。若要换模块，
按 F12/Shift+F12 结束当前采集后再启动下一个菜单。最终回传 bundle 路径、失败摘要、
失败分类、复现命令和当前 SHA；没有真实 HUD 后置就不要宣布 PASS。
```
