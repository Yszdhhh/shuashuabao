# GameScript 当前状态与下一 Agent 交接（2026-08-12）

## 2026-08-12 B 组（感知/素材）云端交付

- 分支：`cursor/b-card-lexicon-bidirectional-1245`（基于 `2067952`）
- 层：感知/素材（未改 mediator / choice_policy / desktop_app / fixtures 真值内容）
- `tools/validate_scenes.py`：接入 `fixtures/card_template_assertions/` 双向断言（正 ≥0.9、空白 ≤0.4、无关帧不得 ≥0.9 误点；`zhufu` 面板命中锁定）
- `config/choice_lexicon.json`：六负面宝物确认在库；补 D0 证实 OCR 别名（箭失* / 全角括号资源名）
- 未伪造新卡图；36 短码与 `fetter_labels.json` 已对齐。等待用户新卡面素材的短码见 `docs/baselines/B_CARD_LEXICON_ASSERTIONS_20260812.md`
- **提醒 C 组**：`FettersCard.tsx` 的 `FETTER_NAMES` 手抄副本需同步或改 API 拉取
- 实机证据：无新增；卡面匹配链路仍需实机抽检（idle_hud 上 14 个旧文字模板 WARN>0.4 但 <0.9）

## 2026-08-12 r11 创房进房回归（当前唯一可测）

- 当前唯一桌面可测版：C:\Users\10639\Desktop\GameScript-v2026.08.12-r11
- 唯一快捷入口：C:\Users\10639\Desktop\GameScript 单人挂机脚本 v2026.08.12-r11.lnk
- r7/r8/r9/r10 已移入：C:\Users\10639\Desktop\GameScript-旧版归档
- r11 EXE SHA256：52FB83E61CC5E221748A8F6698DE1277CBCB8D643AF7E015C0C425F9A3931C1B
- File/Product version：2026.8.12.11 / build_id：2026.08.12-r11
- 配置：1-15、1600x900、dry_run=false、自动创房开、房名/密码为空

### r10 实机失败 → r11 修复

r10 已能打开并识别 584x488 创建对话框（sticky 双窗问题已修），但确认创建后仍报 create dialog confirmation timeout。

根因：create_dialog_probe 在对话框消失后 
eturn max(frames, size)，永远选中更大的平台窗 1328x945，饿死更小的房间窗 ~1224x904，永远看不到 
oom_start。

证据：%LocalAppData%\GameScript-Local\20260812\trace_20260812_102844.jsonl（全程 size 只有 1328/584，无 1224）；incident incident_103102_648_82b61749。

r11 只改捕获排序：创房探测期仍优先独立对话框；对话框没了优先带 
oom_start 的房间窗；否则回落 sticky/signal 排序。**禁止**恢复快速加入 / 房名密码 / blue 创房权限。

落点：Mediator._capture_best()；回归：	ests/test_p0a_create_room_gate.py::test_create_room_phase_does_not_starve_room_window_after_dialog_closes；全量 unittest 通过。

### 验收顺序（r11）

1. 双开 r11 → 自动创房：trace 应见 584x488/CREATE_ROOM → 确认创建 → ~1224x904 + RoomStart（EXE 不因 create dialog confirmation timeout 退出）
2. 选关 1-15 / 到 5/5
3. 完整一局 → 3 局 → 秘境 → 10 局

历史 r7/r10 文档段落保留为快照，**不能覆盖本 r11 状态**。

---

## 0. 后续 Agent 先读这里

本文是 2026-08-12 起的当前状态单一入口。以下文档是历史资料，只能用于理解过程，不能覆盖本文的状态判断：

- `docs/PROJECT_HANDOFF_NEXT_AGENT.md`：2026-08-07 旧基线；
- `docs/NEXT_STAGE_EXECUTION_BLUEPRINT_20260811.md`：重构计划，不是当前实机验收结果；
- `docs/AI_REVIEW_CONTEXT.md`、`docs/LOBBY_AUTOROOM_RESEARCH.md`：含已经过时或过度乐观的描述。

当前工作树是用户连续实测后的权威实现，尚未整理成提交：

- 分支：`codex/ocr-hybrid`
- HEAD：`8b946fa`
- 工作树：16 个 tracked 文件有修改，另有 2 个素材和 2 个测试文件未跟踪；
- 禁止执行 `git reset --hard`、`git checkout --`、批量回滚或覆盖 dirty worktree；
- 后续修改必须先看 `git status --short` 和相邻 diff，只修本次真机证据指出的第一个阻断点。

## 1. 当前桌面发布物

最新版：

- 目录：`C:\Users\10639\Desktop\GameScript-v2026.08.12-r7`
- 快捷方式：`C:\Users\10639\Desktop\GameScript 单人挂机助手 v2026.08.12-r7.lnk`
- EXE：`C:\Users\10639\Desktop\GameScript-v2026.08.12-r7\GameScript.exe`
- File/Product version：`2026.8.12.7`
- SHA256：`A3B8F74EB53441F011B2F989A106EB7169971B256A0162E256DDA14F336C7943`

旧 r5/r6 快捷方式和目录均已移入回收站；桌面只保留 r7。

当前 r7 桌面测试配置（从用户 r6 本轮配置同步，可在看板修改并保存）：

| 配置 | 当前默认值 |
|---|---|
| 关卡 | `1-12` |
| 游戏分辨率 | `1600×900` |
| Dry-run | `false` |
| OCR | `live` |
| 自动创房 | `true` |
| 英雄模式 | 开，难度 `3-4` |
| 胜利后自动挑战秘境 | 开 |
| 房名/密码实验链 | 空，不执行改名或密码输入 |

## 2. 证据等级

后续汇报必须明确使用下面哪一层证据，不得把单测通过写成实机可用：

| 等级 | 含义 | 当前状态 |
|---|---|---|
| I | 已实现 | 多个模块已达到 |
| U | 单元测试/合成回放通过 | 447 tests 通过 |
| R | 真实录像帧离线回放通过 | 秘境进入/失败退出等已有证据 |
| L | 当前桌面版本真机跑通 | **r7 待验证** |
| S | 3 局、10 局无人干预长稳 | **未达到** |

最近全量门禁：

```text
Ran 447 tests in 52.254s
OK (expected failures=2)
```

两个既有 XFAIL 是：

1. `fail_recovery_three_frames`：缺当前版本真实全屏断线/失败弹窗素材；
2. `ticket_zero_archaeology`：缺挑战券为 0 的真实连续三帧证据。

## 3. 当前工作树的主要改动

### 3.1 大厅、创房、选关

- 自动创房走直接创建，不再执行房名/密码实验链；
- 建房点击后必须等待专用建房弹窗锚点，不能凭 SendInput 成功切状态；
- 选关使用同名目标、相邻连续关卡和专用入口做语义确认；
- 当前仅接受游戏窗口 `1600×900`；
- 看板仍可调整目标关卡和英雄模式难度。

### 3.2 r6 紧急创房修复

r5 真机 trace 已确认错误，不是猜测：

- trace：`%LocalAppData%\GameScript-Local\20260812\trace_20260812_001250.jsonl`
- 画面尺寸：`1328×945` 的 KK 平台页；
- 错误动作：连续 3 次 `click:blue_button_color @ (1120,913)`；
- 候选 bbox：`[911,875,180,48]`；
- 后置结果：建房弹窗 3 次都没有出现，最终 `create dialog confirmation timeout`；
- 用户观察：该坐标实际是“快速加入”，会加入别人的房间。

同一次页面中，专用 `create_room` 模板曾以 `0.983` 命中。根因是下一帧模板短暂未命中时，`_find_map_create_room()` 降级为底部蓝色按钮，并把颜色候选错误授予点击权限。

r6 修复：

- `_find_map_create_room()` 只接受 `map_create_room` 专用模板；
- `blue_button_color`、左右位置和按钮数量都不再拥有创房点击权限；
- `config/scenes.json` 的 `map_create_room.fallback` 设为 `null`；
- 新增“两个蓝色按钮同时存在但无创建模板时返回 None”的回归测试；
- 创房专用 19 tests 和全量 446 tests 均通过。

安全含义：r6 即使模板暂时没命中，也只能零输入等待/超时停止，不能再点击快速加入。可用性是否足够仍要本轮真机验证。

### 3.3 r7 局外尺度回归修复

r6 真机 trace `trace_20260812_002654.jsonl` 连续 57 tick 都是 `context=UNKNOWN`、`map_create_room` 无命中、零输入。对应 incident 原帧实际清晰包含创建房间按钮。

根因：1328×945 平台窗口被热路径换算成 `ui_scale=0.83`，但 `map_create_room` 没列入局外绝对尺寸模板集合；生产只搜索 0.83/0.88 倍模板，而按钮资产和页面都是 1.0 倍。旧诊断工具没有模拟生产 `ui_scale`，曾产生 `map_create=True` 的假通过。

r7 修复：

- `map_create_room`、`create_room_confirm` 加入现有 `_L0_GATE_SCENES`，使用 1.0 优先的局外绝对尺度搜索；
- 诊断工具按真实帧尺寸设置 `ui_scale`；
- 新增 1328×945 / `ui_scale=0.83` 回归测试，修复前失败、修复后通过；
- r6 incident 原帧回放命中 `create_room 0.974 @ local(719,871)`；
- 真实窗口只读诊断得到 `ui_scale=0.83 context=PLATFORM_MAP map_create=True`；
- 全量 447 tests 通过；仍未恢复任何蓝色按钮点击权限。

### 3.4 局内两层循环

`src/gamescript/mediator.py` 当前把局内处理分为：

1. 画面状态抢占：选择面板、装备词缀、进化、胜败页等已知高优先级界面先处理；
2. 主动动作循环：`skill → bond → treasure → evolve → equipment → pickup → merchant → artifact`，完成后回到 skill。

已实现但仍需 r7 真机验收的能力：

- 自动主线和四挑战开启；约 120 秒复核一次，明确 OFF 才重新开启；
- G/F/V 选择面板循环；
- 技能只选配置技能，无命中时刷新，次数耗尽后放弃；
- 羁绊基础/接近合成优先，高级羁绊标记与格子占用保护；
- 宝物 OCR/品质回退；
- 进化、装备升级词缀、装备栏吞噬丹/英雄卡、Z 捡取；
- 黑商刷新/购买木材和吞噬丹；
- 神器轮询。

这些能力有单测或录像回放证据，但尚无一份 r7 真机 trace 证明它们在一整局中全部实际发生。

### 3.5 OCR

- 技能、羁绊、宝物接入 OCR sidecar；OCR 只提供名称，不提供点击坐标；
- 选择策略仍为确定性规则，技能 unknown/非配置项不能点击；
- 当前模型和 `.venv-ocr` 位于源码仓库，本机可用；主 EXE 未把 Paddle/模型完整打进包；
- 因此当前 r7 是“本机桌面包 + 本机源码 OCR 运行时”，不是可拷走即用的完全独立包。

### 3.6 胜败退出与秘境

看板新增 `胜利后自动挑战秘境`，保存到 `Settings.auto_secret_realm`，默认关闭。

已实现并通过单测/真实录像帧回放：

- 普通胜利：继续游戏 → 关闭存档面板 → 验证挑战广场 → 退出 → 标准确认 → 返回原房间；
- 普通失败：强失败两帧抢占 → 失败恢复/退出 → 标准确认 → 返回原房间；
- 秘境进入：挑战广场专用大秘境 NPC 右键 → 专用“是” → 等待过渡帧 → 验证秘境 HUD；
- 秘境自然失败：左上专用退出 → 标准退出确认 → 返回原房间；主图已胜利时不会把秘境自然结束计入普通失败三连熔断。

真实录像帧来源：`C:\Users\10639\Desktop\录屏素材\20260810_214444.mp4`。离线回放曾得到：

```text
进入：damijing (1262,247) → mijingOk (713,481) → 过渡帧零输入 → HUD
退出：failure_open_exit (76,58) → exit_confirm_btn (740,554) → PREPARE
```

仍未实现：胜利后自动完成“存档、时光之穴、传家宝”三项挑战。当前只安全关闭存档/传家宝弹窗并处理可选秘境，不得宣称战后三挑战已完成。

## 4. 本轮 r7 真机验收顺序

用户当前正在复跑。不要同时扩功能；先读取最新 trace，只修第一个可复现阻断点。

### 4.1 首先只验创房

1. 手动关闭仍开着的 r5 控制面板；
2. 双击 `GameScript 单人挂机助手 v2026.08.12-r7`；
3. 看板确认标题/日志包含 `v2026.08.12-r7`；
4. 选择普通模式更容易先验主链，关卡 `1-15`，关闭 Dry-run；
5. 平台页只允许出现 `click:create_room` / `CreateRoom-open`；
6. trace 中 **`click:blue_button_color` 必须为 0，快速加入必须为 0**；
7. 建房弹窗必须由专用锚点后置确认，再点击确认创建。

如果 r7 仍只等待不创房，保留现场和 trace；不能恢复蓝色颜色兜底。

### 4.2 一整局主链

依次检查 trace/录像中是否真实出现：

- 创建自己的房间 → 房间开始 → 选择 `1-15` → 进局；
- `EnableAutoTask`；
- 金币/木材/经验/宝物四个 `*-right_click`，任意两次输入间隔不小于 1.5 秒；
- G/F/V 及后续循环动作；
- 进化、装备、Z、黑商、神器至少到期时可执行；
- 胜利或失败退出 → 返回同一个 KK 房间 → 可开始下一局。

### 4.3 秘境

普通一整局通过后，再打开 `胜利后自动挑战秘境`：

- `OpenGreatRift`；
- `ConfirmGreatRift`；
- 挑战广场过渡帧零输入；
- 秘境 HUD 验证；
- 秘境失败两帧抢占；
- `Recovery-FAIL-FAIL_CONFIRM`；
- `Recovery-FAIL-FAIL_EXIT_CONFIRM`；
- 返回原房间并开始下一局。

### 4.4 长稳门禁

严格按以下顺序推进：

1. 1 局完全无人干预；
2. 3 局完全无人干预；
3. 10 局完全无人干预；
4. 才能讨论“长期稳定、多局无人值守”。

任一阶段只要用户手动介入，该次不计入无人值守通过。

## 5. 当前卡点和待验证事项

按优先级排列：

1. **r7 专用创房模板真机稳定性**：尺度回归已在 r6 incident 原帧和当前窗口诊断中修复，尚待真实点击与弹窗后置确认；
2. **r7 一整局动作覆盖**：局内循环功能多，但尚无当前版本全链 trace；
3. **秘境当前版本真机证据**：已实现并用原版录像真帧回放，尚未在 r7 现场跑通；
4. **普通胜败多局闭环**：单测/回放有证据，r7 尚未完成 1/3/10 局门禁；
5. **断线弹窗素材**：`missing_disconnect_modal` 仍缺，相关场景保持 XFAIL；
6. **挑战券为 0**：考古切换缺真实三帧，保持 XFAIL；
7. **战后三挑战**：存档、时光之穴、传家宝自动挑战仍是功能缺口；
8. **LONGZHU/ANCHOR_BOSS/EARLY_CHALLENGE**：未完成安全状态机的旧阶段仍 Fail-Closed；
9. **UIA**：`src/gamescript/ui/uia/` 只有骨架和单测，生产日志仍显示 `l0_uia=disabled`；当前创房走视觉专用模板，不得写成 UIA 已接线；
10. **OCR 可移植性**：桌面包依赖本机源码仓库中的模型和 `.venv-ocr`；
11. **版本可追溯性**：当前重要实现仍在 dirty worktree；真机门禁通过后再整理提交，提交前不得丢现有改动。

## 6. 日志、录像与排查入口

本地自动化 trace：

```text
%LocalAppData%\GameScript-Local\YYYYMMDD\trace_*.jsonl
%LocalAppData%\GameScript-Local\YYYYMMDD\incidents\
```

原版脚本日志：

```text
%LocalAppData%\GameScript\YYYYMMDD\log.log
```

录像：

```text
C:\Users\10639\Desktop\录屏素材\
```

排查时优先读取 JSONL 的这些字段：

```text
build_id, run_mode, settings_summary, context,
phase_before, phase_after, actions, controls,
decision, reason, interrupt_reason, scenes, ocr_suggestion
```

## 7. 后续 Agent 的执行顺序

1. 先读本文、`goal-objective.md`、最新用户描述和最新 trace；
2. 确认用户实际启动的是 r7，不要根据目录名猜版本；
3. 找到第一条错误输入或首次长期零动作的位置；
4. 用真实 trace/帧复现，补一个会在修复前失败的最小测试；
5. 只改对应识别/状态门闩，不顺手扩展新功能；
6. 跑定向测试，再跑全量测试；
7. 升版本、重新构建、校验 EXE FileVersion 和 SHA256；
8. 删除/回收旧快捷方式，只保留清晰版本号；
9. 让用户按 1 局 → 3 局 → 10 局复跑；
10. 真机通过后再提交当前 dirty worktree，并把提交哈希和发布哈希补回本文。

常用命令：

```powershell
git status --short
git diff --stat

$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest tests.test_lobby_detectors tests.test_p0a_create_room_gate -v
.\.venv\Scripts\python.exe -m unittest discover -s tests

powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1
Get-FileHash 'C:\Users\10639\Desktop\GameScript-v2026.08.12-r7\GameScript.exe' -Algorithm SHA256
```

## 8. 禁止的捷径

- 不得恢复地图页通用蓝色按钮点击；
- 不得以“点击发送成功”代替页面后置确认；
- 不得因 OCR unknown 就盲点技能、羁绊或宝物；
- 不得放宽阈值、删失败样本、改分母或新增 XFAIL 来制造通过；
- 不得把录像离线回放、单测或一次人工介入运行写成长期稳定；
- 不得在当前主链未跑通时继续扩存档/时光之穴/传家宝或本地判断模型。
