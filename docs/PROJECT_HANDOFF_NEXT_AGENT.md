# GameScript-Local 项目交接文档

> 交接用途：供下一位外部 Coding Agent 接手 `GameScript-Local` 后继续推进。
>
> 当前交接基线：`e5809b1748dd042f33c53c09732d724d3eeb0838`
>
> 交接日期：2026-08-07

## 0. 先看结论

这个项目已经完成了第一阶段的安全执行链、截图回放门禁、大厅建房/选关链路、局内自动任务、四个挑战按钮和技能三/四选一。

当前最重要的事实不是“功能越多越好”，而是：

```text
识别到可信状态
→ 只生成允许的候选动作
→ 绑定目标 HWND
→ 通过 InputExecutor 执行
→ 读取后续帧确认结果
→ 无法确认时等待、重试或 Fail-Closed 停机
```

任何下一阶段功能都必须沿用这条闭环。不能因为原版资料中存在旧逻辑，就直接把旧的裸输入分支恢复到当前 Mediator。

## 1. 当前 Git 基线与验收状态

### 1.1 提交链

| 版本 | 提交 | 内容 |
|---|---|---|
| P0-A 安全基础 | `26c5a9f` | HWND、帧健康、InputExecutor、急停、真实输入封锁 |
| P0-B1 | `1176097` | 回放与状态机一致性修复 |
| P0-C1 | `54bcdf2` | 未验证战后/大秘境旧逻辑 Fail-Closed 隔离 |
| P1-A1 | `5fc992f` | 自动任务 OFF/ON、技能三/四选一、回放收尾 |
| P1-A2 初版 | `494d5aa` | 四挑战按钮目标化回放与初版自动化 |
| P1-A2 安全返修 | `e540c6d` | UNKNOWN 零输入、右键失败后阻断下游输入 |
| P1-A2 收尾中间提交 | `6384d66` | PENDING 生命周期与项目文档同步；随后被 amend 为最终提交 |
| 当前最终提交 | `e5809b1` | PENDING 生命周期、测试断言与项目文档同步 |

当前 HEAD 是 `e5809b1`，父提交是 `e540c6d`。`6384d66` 是中间提交，不应作为最终交接基线。

### 1.2 当前验收结果

我对当前工作树进行了独立验收，结果如下：

| 检查项 | 独立结果 |
|---|---|
| `python -m compileall src tests tools` | 通过 |
| `python tools/validate_scenes.py` | `ok=99 missing=0 root_unreferenced=0` |
| P1-A2 专项 | `Ran 14 tests ... OK` |
| 全量单测 | `Ran 100 tests in 608.293s — OK` |
| Replay | `Total=27, Passed=26, Failed=0, Required Missing=1` |
| Replay 唯一缺口 | `missing_disconnect_modal` |
| `git diff --check` | 通过；当前没有 tracked diff，只有本交接文档与用户原始素材未跟踪 |

### 1.3 当前工作树状态

当前 `git status --short` 只保留未跟踪文件，没有 tracked 修改：

```text
?? docs/PROJECT_HANDOFF_NEXT_AGENT.md
?? docs/REBORN_WOW_GAME_STRATEGY_RESEARCH.md
?? docs/REBORN_WOW_GAME_STRATEGY_RESEARCH.raw.md
?? fixtures/reborn_wow/
```

其中 `fixtures/reborn_wow/` 和 `docs/REBORN_WOW_GAME_STRATEGY_RESEARCH*` 是用户原始未跟踪素材，必须保持不动。`docs/PROJECT_HANDOFF_NEXT_AGENT.md` 是本次新增的交接文件，尚未提交，但不属于运行代码或 Replay 权威素材。

此前 `6384d66` 与工作树中的 3 处 PENDING 断言曾短暂不一致；该问题已通过 amend 形成最终提交 `e5809b1`，当前 clean HEAD 已包含测试修正。下一位 agent 不需要重复修复这 3 处断言，只需按 H0 做只读基线确认。

## 2. 已完成能力边界

### 2.1 P0-A：运行安全基础

已经完成并有测试覆盖：

- 目标窗口身份包含 HWND、PID、EXE、Class、Role 等信息；
- 截图和输入使用目标窗口绑定；
- 客户区坐标与屏幕坐标转换；
- 黑帧、低熵、冻结帧、旧帧、最小化和捕获失败检查；
- `InputExecutor` 在动作前检查急停、目标 HWND、前台窗口和窗口身份；
- 窗口变化、HWND 无效、急停时取消输入；
- 全局 `Shift+F12` 急停与 Mediator 共享同一个 StopSignal；
- `dry_run=False` 且没有有效目标 HWND 时拒绝真实输入；
- `main.py --legacy` 禁止真实输入，防止绕过安全链；
- Mediator 内的点击、按键、粘贴、滚动均应经过 `InputExecutor`。

P0-A 是所有后续功能的不可绕过前置条件。

### 2.2 P0-B：大厅、建房、房间、选关和 Replay

当前已覆盖：

- KK 地图页识别；
- 创建房间按钮识别；
- 建房弹窗房间名/密码填写，经过 Executor 和 HWND 校验；
- 房间等待页识别；
- 开始游戏按钮识别；
- 关卡列表识别；
- `StageId(chapter, index)` 章节语义；
- 目标关卡精确查找；
- 关卡列表滚动经过 Executor；
- 选中状态验证后才点击开始；
- 不在当前列表时限制滚动次数并 Fail-Closed；
- 取消、快速加入、退出、辅助窗口、黑帧、冻结帧等负样本回放。

当前 Replay 门禁仍有一个必需素材缺口：

```text
missing_disconnect_modal
```

该缺口需要当前版本的完整断线确认弹窗全屏截图。它不是 P1-A2 的阻塞，也不需要为了四挑战功能重复补截图。

### 2.3 P0-C1：未验证战后逻辑隔离

以下逻辑当前不是“部分可用”，而是有意保持安全封锁：

- `archive` 存档挑战入口；
- `boss_entry` 主线 Boss 入口；
- `longzhu` / 传家宝相关旧入口；
- `EARLY_CHALLENGE`；
- `ANCHOR_BOSS`；
- `LONGZHU`；
- 大秘境自动进入。

命中这些未验证入口时，Mediator 必须：

1. 不发送任何点击、右键或快捷键；
2. 进入 `Phase.ERROR`；
3. 调用 `stop()`；
4. 返回 `LoopAction.Break`。

不要把原版旧模板或配置默认值重新接回真实运行。

### 2.4 P1-A1：局内自动任务和技能选择

已完成：

- 右侧“自动任务”复选框使用 `auto_task_off.png` / `auto_task_on.png`；
- OFF 时使用左键开启；
- ON 时零点击；
- UNKNOWN 时零点击；
- 右侧自动任务与左下角四挑战使用不同的控制链；
- 自动任务有最大 3 次重试与 Fail-Closed；
- 技能三选一和四选一使用配置技能偏好；
- 候选数不是 3 或 4 时保持零动作；
- 配置技能找不到时保持零动作；
- 羁绊、宝物和黑商当前保持零动作。

### 2.5 P1-A2：四个挑战按钮

四个目标固定为：

```text
金币 → 木材 → 经验 → 宝物
```

已完成能力：

- 左下角四个挑战按钮模板定位；
- 点击点落在图标区域，不点击文字标签；
- 使用右键开启自动挑战；
- 一个 tick 最多一个挑战输入；
- 明确 ON：绿色“自动”证据达到阈值，零右键；
- 明确 OFF：按钮匹配可靠且状态区域明确无绿色，才允许右键；
- UNKNOWN：状态模糊、遮挡、低置信或缺失时零输入；
- 右键发送后状态转为 PENDING，等待后续帧确认；
- 后续帧看到绿色“自动”才转为 ON 并加入 done；
- 第 1/2 次右键失败时结束当前 tick，下一帧再尝试；
- 第 3 次失败或达到重试上限时进入 ERROR 并停机；
- UNKNOWN 和右键失败都不会泄露到选关分支；
- 新的 MAIN_LINE 会话四个挑战显式初始化为 PENDING；
- PENDING / OFF / ON / UNKNOWN 有针对性回归测试。

当前实现的核心调用链位于：

```text
src/gamescript/mediator.py
  _resolve_challenge_state()
  _ensure_challenge_buttons()
  _tick_main_line()
  set_phase(Phase.MAIN_LINE)
```

## 3. 当前明确未完成的功能

下一位 agent 不得把下面这些项目当成已经恢复：

| 功能 | 当前状态 |
|---|---|
| 胜利后继续游戏 | 有用户截图和原版线索，但未形成当前版本安全状态机 |
| 存档挑战 | 未实装执行代码，保持 Fail-Closed |
| Boss 挑战选择 | 未实装执行代码，保持 Fail-Closed |
| 传家宝挑战 | 未实装执行代码，保持 Fail-Closed |
| 大秘境入口确认 | 未完成前置校验，禁止自动进入 |
| 黑商购买 | 当前零动作 |
| 羁绊选择 | 当前零动作 |
| 宝物选择 | 当前零动作 |
| 断线弹窗恢复 | 缺少 `missing_disconnect_modal` 素材，尚未解封 |
| 视频级行为复原 | 外部研究已回传，但尚未形成逐帧 Replay 标注管线 |

外部策略研究只作为候选规则资料，不能直接改变默认配置或真实输入行为。

## 4. 权威文件和素材关系

### 4.1 代码入口

| 路径 | 用途 |
|---|---|
| `src/gamescript/mediator.py` | 当前运行状态机和输入前置条件 |
| `src/gamescript/input/keyboard_mouse.py` | `InputExecutor` 与动作安全检查 |
| `src/gamescript/vision/capture.py` | 截图、Frame 和帧健康检查 |
| `src/gamescript/vision/stage_selector.py` | StageId、关卡行识别和选中验证 |
| `src/gamescript/settings.py` | 配置加载与默认值 |
| `config/scenes.json` | 场景与模板注册 |
| `config/default_settings.json` | 默认配置，特别注意安全默认值 |
| `tools/run_replay.py` | 根 Replay 门禁和动作类型断言 |
| `tools/validate_scenes.py` | 场景模板静态校验 |
| `fixtures/manifest.json` | 当前可执行 Replay 的权威清单 |

### 4.2 素材规则

必须区分两套素材：

- `fixtures/manifest.json`：根 Replay 权威清单，`run_replay.py` 实际读取这里；
- `fixtures/reborn_wow/`：用户当前版本原始截图和外部研究证据，当前是未跟踪素材，不能直接当作已注册 Replay；
- `fixtures/replay/`：已纳入根 Replay 的可执行回放素材；
- `assets/Images/`：代码运行时使用的模板资产；
- `docs/REBORN_WOW_GAME_STRATEGY_RESEARCH*`：外部研究原文和原始资料，禁止在功能开发中擅自改写。

没有必要时不要新增截图。已有 P1-A2 功能不需要用户重新上传挑战按钮截图。

## 5. 安全不变量

下一位 agent 修改任何功能前，必须保持以下不变量：

1. `dry_run` 默认继续保持安全；未经过验收不得做真实输入短跑。
2. 真实输入必须经过 `InputExecutor`，不得从 Mediator 或新模块直接调用底层裸输入。
3. 每个真实动作必须有有效目标 HWND；窗口变化、前台窗口不符或急停时必须取消。
4. 不健康帧不得产生决策或输入。
5. UNKNOWN 不得产生动作。
6. PENDING 只表示等待确认，不表示已完成。
7. 右键发送成功不等于挑战已开启，必须等待后续帧确认。
8. 任何危险动作必须有前置识别和后置确认。
9. 未验证战后、Boss、传家宝、大秘境入口必须 Fail-Closed。
10. 不允许用固定坐标替代当前已有的模板、ROI、窗口绑定和动作后置条件。
11. 不引入 OCR、ML、内存读取、DLL 注入、网络协议修改或第三方依赖，除非项目负责人另行授权。
12. 一次只处理一个清晰主题，提交一个清晰 commit。

## 6. 下一位 agent 的第一条任务

### H0：只读确认 P1-A2 基线

这是交接后的第一步确认，不是代码修改任务，也不是新功能开发。

要求：

1. 确认 HEAD 是 `e5809b1748dd042f33c53c09732d724d3eeb0838`；
2. 确认 tracked working tree clean；
3. 确认 `tests/test_p1a2_challenge_controls.py` 中 PENDING 断言已经在 HEAD 内；
4. 不删除测试、不降低断言、不修改用户未跟踪素材；
5. 如没有代码变更，先运行专项门禁和静态检查，不要为了产生 commit 而制造 commit；
6. 回传当前 commit、工作树状态和检查结果；
7. 只有完成 H0 验收后，才开始下一条任务。

H0 的目标是确认“通过 100 个测试”的状态存在于可复现的干净 commit 中，而不是只存在于 dirty worktree。

## 7. H0 之后的建议路线

### P1-B0：战后状态只读建模与 Replay 证据闭环

下一阶段不要直接恢复 Boss 或大秘境点击。先做只读观察和证据整理：

1. 读取已有胜利结算、继续游戏、存档挑战、传家宝、大秘境截图；
2. 为每个页面定义 `CONFIRMED`、`INFERRED`、`UNKNOWN`；
3. 建立状态转换图，但默认只允许输出候选动作，不发送真实输入；
4. 为已存在截图建立根 Replay 条目或独立只读诊断；
5. 明确每个入口的前置条件、禁点区域和后置确认；
6. 先验证“不会误触”，再讨论“如何自动点击”。

建议的状态链：

```text
MAIN_LINE
  → VICTORY_MODAL
  → CONTINUE_GAME
  → ARCHIVE_PANEL / HEIRLOOM_PANEL / SECRET_REALM_PROMPT
  → 只读识别与证据记录
```

H0 未验收前，不要开始 P1-B0。

### P1-B1：战后入口安全状态机

只有 P1-B0 的截图和 Replay 证据足够时，才进入：

- 存档挑战逐项选择；
- Boss 配置选择；
- 传家宝挑战选择；
- 大秘境“地图清空 + 英雄挑战存在 + 确认弹窗”三重前置；
- 每一步均需后置帧确认；
- 任意 UNKNOWN、窗口变化或前置条件缺失都 Fail-Closed。

不能把 `fixtures/reborn_wow/` 中的用户截图直接当作已经验证的行为。

## 8. 外部 agent 通用工作提示词

下一位 agent 接手后，先复制下面这段作为工作约束：

```text
你正在接手 GameScript-Local。

先阅读：
1. docs/PROJECT_HANDOFF_NEXT_AGENT.md
2. docs/PROJECT_BLUEPRINT.md
3. docs/ORIGINAL_1_3_8_BEHAVIOR_MATRIX.md
4. 当前 HEAD 对应的 src/gamescript/mediator.py
5. tests/test_p0_security.py
6. tests/test_p0b1_fixes.py
7. tests/test_p0c1_fixes.py
8. tests/test_p1a1_main_line_controls.py
9. tests/test_p1a2_challenge_controls.py

当前基线：e5809b1748dd042f33c53c09732d724d3eeb0838。

第一条任务只能做 H0：只读确认当前基线、工作树和门禁结果。
不要重复修改已经完成的 PENDING 断言，也不要开始战后、Boss、传家宝、大秘境、黑商或新策略功能。

保护规则：
- 不修改 docs/REBORN_WOW_GAME_STRATEGY_RESEARCH*；
- 不修改 fixtures/reborn_wow/；
- 不使用裸输入；
- 不关闭 dry_run；
- 不引入第三方依赖；
- 不改写 Git 历史；
- 不通过放宽或删除测试来制造通过结果。

H0 确认时运行：
python -m compileall src tests tools
$env:PYTHONPATH="src"; python -m unittest discover -s tests -v
$env:PYTHONPATH="src"; python tools/validate_scenes.py
$env:PYTHONPATH="src"; python tools/run_replay.py
git show --check HEAD
git diff --check HEAD~1 HEAD

回传：当前 commit hash、是否有 tracked 修改、每条命令真实退出码、全量测试数量、Replay 摘要、git status。
只有 H0 被项目负责人验收后，才接收下一条任务 P1-B0。
```

## 9. 当前不需要用户补充的资料

P1-A2 的四个挑战按钮、自动任务 OFF/ON、技能三/四选一不需要重新截图。

当前真正缺少的截图只有：

```text
当前版本完整断线确认弹窗全屏截图：missing_disconnect_modal
```

如果后续推进 P1-B0，可能需要用户补充或重新采集战后页面的连续帧，但必须先由 agent 给出明确的页面缺口、用途和采集时机，不能笼统要求用户“再发一遍截图”。

## 10. 最终交接判定

当前项目可以作为“功能和安全基线”交给下一位 agent 阅读和继续推进。最终交接基线是 `e5809b1`；`6384d66` 仅作为被 amend 替代的中间提交记录。

交接顺序必须是：

```text
确认 e5809b1 是干净基线
→ H0 全量验收
→ P1-B0 战后只读状态与 Replay 证据
→ P1-B1 战后安全状态机
→ 最后才评估真实输入短跑
```
