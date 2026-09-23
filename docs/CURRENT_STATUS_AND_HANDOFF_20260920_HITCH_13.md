# 13 号蹭车完整链路交接（2026-09-20）

## 本轮结论

当前 13 号默认试跑为：`1 局真实蹭车 → 离房 → 自建单人房 → 选关页点击考古 → fresh kaogu/kaoguMode 锚点确认 → 退出脚本`。

13 号启动时会只读加载正式看板，再生成临时设置副本，强制写入：

- `hitch_cycle_num` / `cycle_num` 默认是 `1`（兼容 production runtime 的通用局数字段）
- `hitch_after_goal=arch`
- `auto_archaeology=true`

这是为了先验证“退出切入考古”链路；正式 `C:\Users\10639\AppData\Local\ShuaBao\user_settings.json` 不会被测试启动器改写。需要长链时，在启动器进程环境设置 `SHUABAO_HITCH_E2E_ROUNDS=5`，不设置则保持快速 1 局试跑。

## 生产收尾链路

`Mediator._finish_hitch_round()` 在目标局完成后设置离房与考古 handoff 标记；先完成旧房真实退出和回厅，再复用已有单人选关路由。考古按钮点击后必须拿到新一代 `kaogu`/`kaoguMode` 页面锚点，确认成功才 `COMPLETE` 并停止脚本。没有 fresh 锚点时只等待，不算 PASS。

## 今天已确认的蹭车问题与修复

1. 13 号之前实际读取的是看板局数；本轮用隔离副本默认 1 局 + 考古收尾，专门验证退出切入链路。长线程通过 `SHUABAO_HITCH_E2E_ROUNDS` 切换，不再改代码。
2. 蹭车链仍由 production `Mediator.tick()` 驱动，capture harness 只观察 trace/状态并汇总，不复制搜房、进房、Ready、压力、结算或回厅 FSM。
3. 单人考古直达曾在 `BOOT` 阶段过早设置 handoff，导致房间页安全零输入；已在 `7ab6e27` 延后到 production 进入 `STAGE_SELECT` 后再 arm。
4. 选关页的考古模板曾误用 `1-23` 关卡行残片，导致“考古模式”假命中；已在 `173dd8a` 替换为真实按钮模板，并更新运行时资源清单。该模板在实机 bundle 上命中 `1.000`，独立截图复核 `0.970`。

## 13 号验收标准

必须同时满足：

- `rounds_started == 1` 且有真实 `ROOM_LIST → JOIN → READY → PRESSURE → OUTCOME → REAL_EXIT → LOBBY_RETURN` 证据；
- 至少一次 blocking modal recovery，且无 UNKNOWN 输入、静默停止、永久零输入 stall 或盲点回家；
- 第 1 局后出现 `ARCHAEOLOGY_HANDOFF_CONFIRMED`，并能在 manifest 中看到 fresh `kaogu`/`kaoguMode` 锚点；
- capture summary 的 `natural_e2e` 为 `PASS`。仅点击成功、单帧变化或人工点房间/准备/退出均不算通过。

## 操作

1. 通过桌面快捷方式打开 `刷刷宝 Live 实机测试.lnk`。
2. 先点“1 启动前检查”，确认 `READY FOR GT: YES`。
3. 点击“13 PRIMARY HITCH_FULL_NATURAL_E2E”。启动器会显示临时设置副本路径，随后进入一局退出切考古试跑。
4. 测试期间不要手动点房间、刷新、准备、开始、压力、背包或退出；紧急停止使用 `Shift+F12`。
5. 交接时提供生成 bundle 目录，重点查看 `manifest.json`、`trace` 和 `failures`；若未到 `ARCHAEOLOGY_HANDOFF_CONFIRMED`，只能记为未完成/阻塞，不能记 PASS。

## 当前待真机确认

本次代码和离线契约已完成；当前先用 13 号按钮跑一条新的 1 局实机 bundle，确认退出切入考古。通过后设置 `SHUABAO_HITCH_E2E_ROUNDS=5` 验证密钥挑战、传家宝、时光之穴等可选路线。此前的单人 14 号问题不能代替 13 号真机 PASS。

## 2026-09-22 长线程异常收尾补充

昨晚长线程在第 11 个房间遇到“等待 1 号位选择难度”超时。该页面是已识别的客号预开局页，但没有常规局内左上退出按钮；旧 QUIT 分支将其降为 UNKNOWN，15 秒后以 `exit button timeout` 停止。

已补齐：该已知页面找不到专用退出按钮时，只发送一次语义 `Esc` 并进入既有确认/回房观察链；取得 fresh 房间证据后拉黑该房并**继续搜房**（Owner 2026-09-22 裁定：单个房主磨蹭不得提前结束长线程；考古只由 cycle_num 达标 / 挑战券预算触发）。该异常不增加 `game_count`，不扣挑战券。

已知限制：客号全程看不到选关页，`_ticket_balance` 恒为 None（fail-open），蹭车模式下"门票耗尽转考古"不会触发，长线程终点只能由 cycle_num 决定。

搁置：同批次的「诅咒之力/提高上限 默认不拿」改动未提交——违反 `test_treasure_negative_fixtures_contract`（每张负面卡须 ≥1 真机面板帧），待补实机帧后单独提交。

离线验证：`python -m pytest tests/test_hitch_guest_stage_select_recovery_20260921.py tests/test_s0_hitch_failure_exit.py tests/test_ticket_budget_20260921.py tests/contract -q` → `86 passed, 111 subtests passed`（Owner 裁定后重跑）。

仍需真机：在房主选难度页超过阈值后，确认 `Esc → 退出确认/平台房间 → 拉黑并继续搜房` 的实际 UI 变更；若 `Esc` 未产生可观察变化，保持零输入并记录为 BLOCKED，不把点击发送当作成功。

## Owner 待裁决（本任务只记录，不改代码）

1. `hitch_after_goal="solo"` 的看板标签是“去单人刷票”（`main_window.py:2810`），但 `_finish_hitch_round()` 当前实现为 `COMPLETE + stop + Break`，实际直接结束脚本，没有进入单人刷票。预期应有“考古 / 单刷 / 结束脚本”三个分支，目前只有两个且其中一个名不副实。
2. `auto_create_room=True` 当前只写在 `arch` 分支内。按“目标局数到达后即解禁”的语义，应移到达标判断之后、分支判断之前；本轮 arch 不暴露问题，因为其他分支直接停止。

## 2026-09-20 20:45 bundle 复盘

`C:\tmp\shuabao-captures\hitch_lobby_chain_20260920_204522_885047` 已确认 `game_count=5`、`victory_count=5`。第 5 局退出确认点击成功，但随后旧房页面持续被识别为 `ROOM_WAITING`，最终因 UNKNOWN 输入保护而 FAIL。

根因有两层：

1. 旧房退出兜底直接取全屏最高分的 `room_exit_btn`，在这轮命中了房间内容区（约 `(731,261)` / `(768,344)`），没有命中右下角真实“退出”按钮，所以没有产生 fresh 房间列表；
2. 13 号蹭车阶段为禁止自建房会把 `auto_create_room=false` 投影到内存设置。即便离房成功，收尾只切到 `normal_farm` 也不足以进入自建房考古路由。

已修复：旧房收尾改用 `_find_hitch_exit_button()` 的右侧房间几何约束；`hitch_after_goal=arch` 收尾显式恢复 `auto_create_room=true`。下轮应看到“真实退出 → fresh 房间列表 → 自建房 → 选关考古”，而不是停在旧房。

## 2026-09-22 Boss 后置语义最小收口（恢复与战后层）

视觉验收（`G:\刷刷宝\_facts_20260922\mechanics_solo\BOSS_VISUAL_ACCEPTANCE_20260922.md`）撤回旧「掉落弹窗/击杀BOSS=受理」结论。双帧未识别到卡 **只支持停止重复定位/空滚**，不证明受理或成功。

改动（`src/shuabao/mediator.py` 两条调用路径 + 测试 + `docs/BOSS_CHALLENGE_20260922.md`）：

- 双帧无卡时：`_time_cave_boss_done=True`、`_time_cave_boss_result_confirmed=False`、`_time_cave_boss_confirm_unconfirmed=True`、`_time_cave_boss_clicked_at=None`
- 不新增 list_closed / 掉落 OCR / 战果识别；保留有界滚动、无锚点零输入、卡片重现重置、超时 incident

仍需实机：业务受理/成功锚（掉落条或战果 HUD）；tick4081 拒点窗；game_count 映射；六次兜底时 17 解锁状态。验收目标是「收敛不虚报受理」，不是 Boss 实机成功。

## 2026-09-23 单人长线程蹭车复盘与恢复修复

实机 bundle：`G:\刷刷宝\captures\hitch_lobby_chain_20260923_005558_114522`。

复盘结论：设置目标为 20 局并在达标后切考古，但本次只完成 3 局；第 4 个房间的房主选难度页随后变成“即将开始/加载”画面，没有出现局内 HUD。页面状态标签滞后，最终由通用无进展退出进入 QUIT；该加载画面没有退出按钮，导致 `exit button timeout`，进程在 01:37:43 结束。没有达到 20 局，也没有触发考古。

已修复：

- 保留已观察到的房主选难度生命周期；进入无 HUD 的开局/加载画面后单独计时 180 秒，仍无 HUD 时拉黑房间并进入未开局退出链。
- 已知选难度/加载生命周期内屏蔽通用 UNKNOWN 看门狗的提前 Esc，避免它抢在专用超时前误发按键。
- 对已知开局/加载画面使用一次语义 Esc；确认仍不可见时沿用现有退出链的有限重试预算。必须等 fresh 平台房间证据才完成退房；中止房间不增加局数、不扣门票，也不触发考古。
- 门票模型维持每局 2 张；逐局简报记录蹭车开局/完成数、胜负、章节-关卡（如 `2-7`）、有证据的挑战动作、估算门票消耗/余额及单刷完成数。
- 章节-关卡优先读取局内 HUD 右上方的 `2-7` / `1-21` 标识；紧邻的 `第2/5波` 是当前波次，不参与统计。选关页只有唯一高亮时才作为 HUD 未读到时的备用值。

实机原始帧票数：`f0045` 为 `130/130`，`f0250` 为 `128/130`，`f0502` 为 `126/130`，`f0798` 为 `124/130`，每把减少 2 张。前一版门票 ROI `(1067,850)-(1102,888)` 在这些截图上被 OCR 高置信读成 `301/281/261/241`，根因是裁剪范围跨到了票数文本边界；这不是可用的余额，也不能据此推算每局 20 张。现将读取 ROI 缩到当前票数数字，原始帧 OCR 校准为 `130/128/126/124`。蹭车只有实际看到选关页时才会更新实时余额，其他阶段依然用每局 2 张死算。

离线验证：蹭车恢复、票数预算、HUD/简报用例 `43 passed`；共用退出与平台看门狗 `25 passed`；层间合同 `66 passed, 231 subtests passed`。这些只验证状态机和格式化逻辑，不代表新退出链已通过实机确认。

实际帧复核：恢复调用既有 `detect_ingame_stage_label` 后，本 bundle 多张局内 incident 前/后帧均稳定识别为 `2-7`；选关页单看亮边仍会同时命中 `1-1` 与 `1-9`，因此以局内 HUD 标签为准，不让这处选中边框歧义覆盖准确读数。

### 2026-09-23 实机画面复核修正：第 4 房实际进入组队考古

复看 `incidents/incident_013500_650_dcd6f142/frame_before.jpg` 后，前一节“第 4 房一直未出现局内 HUD”的结论不完整：画面顶部明确显示“考古模式”，中央有“考古中”计时。生产锚点 `_archaeology_mode_anchor()` 在该实机帧命中 `kaoguMode`，score `0.922`。运行记录仍是 `game_count=3`，也没有 goal handoff；因此这是提前加入了组队考古房，随后旧退房链因退出按钮识别超时而报错，并非达到 20 局后正常切考古。

已按用户规则补上处理：蹭车模式在目标局数前识别到 `kaoguMode`，就拉黑该房并走未完成房间退出事务；退出按钮缺失时发送语义 Esc，再等待房间/大厅 fresh 证据。离开后留在 `lobby_hitch` 继续搜房，不增加完成局数、不推进门票扣减、不触发考古 handoff。若检测发生在主线统计已记账之后，会撤回该房的临时开局数与章节计数。选关页右下角的普通 `kaogu` 按钮不是此检测依据。

离线回归新增覆盖了提前进入组队考古、主线统计回滚，以及无退出按钮时 Esc 后回大厅继续搜房；相关测试通过。真实退出和再搜房仍需下一次实机确认。

### 2026-09-23 关卡读取口径再次更正

用户给出的 HUD 截图明确展示右上 `1-21` 章节-关卡，旁边 `第2/5波` 是独立的波次字段。先前把 `detect_ingame_stage_label` 一并排除是错误的；该既有识别器读取的是章节-关卡区域。本次在原 bundle 的多张实际局内帧上回放，结果均为 `2-7`。蹭车统计现优先从局内 HUD 读取章节-关卡，持续观察直到读到，完成离局时仍未读取才回退到唯一高亮的选关页候选。

### 2026-09-23 UI 固定窗口预览交接（未发布）

- 正式主目录 `G:\刷刷宝\GameScript-Local` HEAD 为 `94f502335dd3575926fc78e853f992edbb401fab`，工作区含大量其他未提交改动；`%LOCALAPPDATA%\ShuaBao\current.json` 的 `current_source_sha` 仍是同一旧 SHA。不得把本轮 UI 预览称为正式包或实机验证。
- UI 分支 `G:\刷刷宝\Worktrees\ui-run-summary-20260923` 位于 `feat/ui-run-summary-20260923`，HEAD `7070c0970cc31406684b71a318c3ea123f0b91f1`。本轮在该分支和主目录的 `ui-v2/index.html` 各加了相同的未提交 CSS 修复：上排 grid 行改 `max-content`，1080×820 时压缩少量组标题/底部留白，消除宝物覆盖羁绊。不要覆盖主目录其余已有改动。
- 桌面 `刷刷宝 UI预览（不连接游戏）.lnk` 已改指向 `G:\刷刷宝\GameScript-Local\.venv\Scripts\pythonw.exe` + `G:\刷刷宝\Preview\固定窗口预览.py`。它用 Qt WebEngine 固定 1080×820、缩放 1.0，加载本地 Vite dev/mock bridge，不连真实游戏/订阅。原 `刷刷宝 实机测试台.lnk` 未改，仍钉住旧 SHA。桌面 `刷刷宝 固定窗口预览.png` 是实际 Qt 窗口截图；UI 窗口已启动并经 Windows 窗口树确认。
- 本轮 UI `npm run check`、`npm test`（61 passed）、`npm run build` 均通过；固定窗口截图确认 1080×820、zoom 1、无宝物/羁绊重叠。完整 `release_gate.py` 在 pytest 阶段因用户要求立即交接而中止，不能记 PASS；本轮 CSS 后尚未生成、签名或部署新的正式 EXE。
- 下一位先审设计与交互；若要发布，按 `AGENTS.md` / `RELEASE_HARNESS_LESSONS.md` 在主目录完成门禁、正式构建、签名及桌面源码/产物/快捷方式 SHA 核对。不要用 Qt mock 预览或旧 EXE 冒充正式验收。

### 2026-09-23 设计系统整合（仅文档/设计资产，未改代码）

- 新建 claude.ai 设计系统「刷刷宝」：https://claude.ai/artifact/SJA8b2B75KxVso7RDMwMGk 。令牌取自 UI 分支 `7070c097` + 未提交布局修复在 Chromium 1080×820 下渲染后的**实际生效值**（`.win` 计算样式），含深/浅主题、四套主色方案（默认钛银 titanium）、字样、间距/圆角/阴影、6 个静态组件还原。代码仍是唯一权威，设计系统随代码同步。
- 9 月 17 日设计画布「刷刷宝看板 UI 升级」https://claude.ai/artifact/9gRtjqrUwtxkV1CL4J39t2 是早期方向稿（1280×800、香槟金、Apple 系配色），与代码冲突处以代码为准；其动效四档时长/曲线尚未进代码。
- 本轮只读核对：主目录 ui-v2 四个文件与 UI worktree 内容一致（`7070c097` 内容 + 同一 CSS 修复），未提交、未构建、未发布。

### 2026-09-23 UI 升级稿（UI 分支未提交，未构建/发布）

- 位置：`G:\刷刷宝\Worktrees\ui-run-summary-20260923\ui-v2`，改 `index.html`（新增「补丁 UI-24」CSS/JS 与少量源码改动）、`src/bridge/mockBridge.ts`（仅 mock：广播 `sb:window-layout` 供预览框模拟窗口尺寸）、`tests/ui23_regression.spec.ts`（宝物分组摘要断言随新行为更新）。主目录 `ui-v2` 未同步，发布前需合并 UI 分支。
- 内容：同层面板底对齐；宝物设置手风琴（同时只开一组）、「默认不拿」移到标题小字、分组两列、龙珠改线性图标；篇章名/阶段分列；高级卡组空态、拖动 + ▲▼ 紧凑排序、超过 3 个分两列；编辑羁绊时技能/宝物收成一行；带车房间压成两行避免左栏溢出；声望任务列表加宽；小窗隐藏多余分隔点。
- 验证：云端 bun 构建 + Chromium 1080×820 / 360×实测高截图；bun 跑 61 个前端测试 60 过，1 个失败是 bun 的 vi 缺 `advanceTimersByTimeAsync`（与改动无关），须在本机 `npm test` 复核；`tsc --noEmit` 通过。未跑 `release_gate.py`，未构建正式 EXE。
- 在线预览（模拟数据）：https://claude.ai/artifact/6sz4fkc3s6SJkmrwe4MSxP ，蹭车/跟车会按正式宿主缩成 360 宽小窗。
- 追加（同日）：宝物效果说明改为挂在 `.win` 上的浮层（不再被分组/面板 overflow 裁掉，去掉重复的系统 title 提示）；修复「补丁 F–I」作用域缺 `reduce()` 导致激活成功动画报错不播放；标题栏订阅胶囊只写「卡密有效 · MM-DD 到期」，LIVE 状态进悬停提示；新增 ≤1000px 宽度适配（技能卡随面板宽、高级卡组隐藏拖柄），为收窄看板做准备。`_DASHBOARD_SIZE` 仍是 1080×820，待 Owner 在预览里比较 1080/1000/960 后再改外壳。仅 http 预览页暴露 `window.__sbPreviewState` 给场景条，file/qrc 正式包不暴露。
- 追加：看板改为 960×820。UI 分支改了 `src/shuabao/shell/web_config_shell.py`（`_DASHBOARD_SIZE`、看板标题栏拖动区 360 宽）与 `tests/test_web_config_shell.py`（尺寸与拖动区断言），`G:\刷刷宝\Preview\固定窗口预览.py` 的 SIZE 同步为 960。原 dashboard 拖动区为 `宽 - 230`（1080 时 850），实测标题栏右侧控件从 x≈371（960 宽、订阅已激活）开始，旧值会盖住订阅胶囊/方案下拉/保存方案等按钮的点击，需实机确认旧正式包是否受影响。另：技能卡策略下拉 124px 不再压住 ▲▼；策略列表各行同宽；过场卡顿主因是彩色边框流光（两张 1600² 锥形渐变 + 全窗 inset 阴影现场栅格化），已改为 400² 放大旋转 + 渐变内晕，完成过场栅格耗时约减半；关闭 30 余处无视觉作用的 backdrop-filter。Python 测试未在本机跑，需 `python -m pytest tests/test_web_config_shell.py -q` 复核。
- 追加：UI-24 交接提示词已落在 UI 分支 `ui-v2/docs/UI24_HANDOFF_PROMPT_20260923.md`（入口指针 `G:\刷刷宝\handoff_prompts\UI24_看板升级_交接入口_20260923.md`）。桌面预览快捷方式改为调用 `ui-v2/_verify/preview_window.py`（960×820 + 场景面板 + 小窗缩放），场景动作统一在 `ui-v2/src/dev/previewScenes.ts`；浏览器沙盒 `ui-v2/_verify/preview_sandbox.html`。订阅胶囊有效态改为中性配色 + 绿色状态点。
