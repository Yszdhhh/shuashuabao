# 云审查请求：GameScript-Local 中断问题系统性根因（2026-08-09）

> 目的：用户反馈"脚本自动中断退出问题反反复复修了很多遍都没解决"，请云端 AI 做**系统性根因审查**，找出反复中断的模式性原因与遗漏的中断源，输出防御与诊断改进建议。只读审查，不要求改代码。

## 1. 项目与运行环境（一句话版）

- 仓库：GameScript-Local（Python + OpenCV + PySide6，纯视觉识别 + Win32 输入链）
- 游戏：KK 对战平台魔兽RPG《懒人系列之魔兽世界刷刷刷》v1.3.x（CEF 渲染，基准 UI 1600x900）
- 输入链：InputExecutor（UAC 提权 → HWND 校验 → 前台激活 → WindowFromPoint 遮挡拒绝 → SendInput 返回值检查 → 一帧一动作）
- 运行方式：`dist\GameScript\GameScript.exe`（管理员）；dry-run 观察模式 = 只识别不点击
- 全量测试 159 绿（2 个 XFAIL 缺实机证据）；场景回放 harness（FakeClock/FakeInputExecutor，每 tick 六项硬断言）
- JSONL tick trace（logs/trace_*.jsonl）：tick/phase/context/hwnd/size/actions/scenes/elapsed_ms

## 2. 中断问题完整历史（按时间，全部有提交证据）

| # | 日期/提交 | 症状（实机） | 根因 | 修复 |
|---|---|---|---|---|
| 1 | 08-06 输入实验 | 合成输入全无效（diff≈0.0） | 游戏更新后拒绝用户态合成输入（mouse_event/SendInput/PostMessage 全被忽略），仅物理鼠标有效 | 结论存档：全自动需驱动级输入（未批准）；未修 |
| 2 | 08-07 frozen/old_frame 误杀 | 弹窗/慢捕获静态帧被判坏帧，15s 停机 | 帧健康检查把 {frozen,old_frame} 静态帧当坏帧 | 仅 {frozen,old_frame} 判定为良性静态帧，放行识别（黑帧/低熵/无窗口仍 15s ERROR） |
| 3 | 08-08 acb1755 | "一进游戏就停"：ROOM_STARTING 后 context=UNKNOWN → 回退 → 平台窗消失 → ERROR | 游戏窗口 960x540（=0.6x 基准），模板 scales 0.85-1.2 全不命中 → 识别失败；且 ROOM_STARTING 超时误回退到已消失的平台房间页 | 会话级 ui_scale 校准（scales 并入 ui_scale 邻域）；ROOM_STARTING 窗口已出现时不回退 |
| 4 | 08-09 57d40ce（云审查 P0/P1） | （静态审查发现的潜在中断） | api_server 双 worker 竞态可双实例注入输入；fail 恢复一帧多动作；多显示器坐标错误；SendInput 返回值未检查；选择面板 UNKNOWN 盲点/全库扫描；STAGE_STARTING 守卫不一致；Settings 非法值 | 四态 RunnerState+generation；RecoveryState 一帧一动作；VIRTUALDESK；CANCELLED_SENDINPUT_FAILED；preferred-only 决策；统一 _is_in_game_hud；Settings 范围表+原子写 |
| 5 | 08-09 7db8890（今天，用户 dry-run 实测） | 局内正常游戏时 phase MAIN_LINE → QUIT fail/disconnect → 退出链 → 超时 ERROR | **选择面板"放弃"按钮与失败弹窗 giveUp 模板同源（0.945 误命中）**：羁绊/宝物选择面板弹出即误判失败 | 选择面板存在（_selection_anchor）时跳过 fail/disconnect 检测 |
| 6 | 08-09 7db8890（今天） | CREATE_ROOM 后窗口短暂消失（用户手动关弹窗/切窗口）15s 即 ERROR | 无窗口容忍仅 min(query_timeout,15) 太激进 | CREATE_ROOM/PLATFORM_MAP 容忍对齐 BOOT（30-60s） |
| 7 | 08-09 57d40ce 设计 | （潜在）未知选择面板零输入 10s 后 Fail-Closed ERROR | 面板存在但无偏好命中且品质色不可识别 → 10s 停机（设计如此，防盲点） | 设计保留；实机是否过严待评估 |

## 3. 用户的核心质疑与我们的初步假设

"中断问题反反复复修了很多遍都没解决" —— 请验证/反驳以下假设：

1. **症状级修复循环**：每次修复都是针对一个具体中断点（识别、窗口、误检），可能遗漏模式性根因（如：窗口/前台状态在用户操作与脚本检测之间的竞态）
2. **中断源分散但缺乏统一防御**：中断入口包括——不健康帧、fail/disconnect、未知面板、超时回退、输入拒绝、页面异变；是否缺少统一的"中断分类 + 降级策略 + 诊断闭环"（trace 是 08-09 才加的，此前中断只能靠 print 日志）
3. **dry-run 观察模式与真机的行为差异**：dry-run 下用户手动操作，窗口/弹窗状态变化频繁，脚本的"窗口消失即 ERROR"等策略在观察模式下过严——观察模式应该有独立的宽松策略（不中断、只记录）？目前没有。
4. **fail/disconnect 检测的模板可靠性**：giveUp 模板与选择面板按钮同源，其他 fail 模板（fail/gameFail/gameDisconnect/retryConnect）是否也有误命中面？真实失败弹窗的证据缺失（fail_recovery_three_frames XFAIL）。
5. **960x540 vs 1600x900 双分辨率并存**：用户有时 1600x900 有时 960x540，ui_scale 校准是否覆盖所有检测器（有些 find_scene 固定 scales）？

## 4. 请重点审查的问题

1. 中断链路全枚举：从"进游戏"到"结束"，列出所有可能 ERROR/Break 的出口（代码级），哪些缺实机证据、哪些策略过严
2. fail/disconnect/RecoveryState 的触发条件是否足够保守（误检面）与足够敏感（漏检面）？缺真实弹窗证据的情况下如何安全收紧
3. dry-run 观察模式是否需要独立策略（如窗口丢失不 ERROR、只标记）——观察模式是用户当前主要使用方式
4. 一帧一动作与超时/回退的组合是否还有竞态（动作后立即超时回退、旧帧决策等）
5. trace JSONL 是否够诊断中断（缺什么字段：窗口枚举结果、健康检查详情、失败原因分类）
6. 测试覆盖盲区：159 测试里哪些中断路径没有场景测试（列出缺的场景）
7. 代码级：mediator.py 约 2500 行，中断相关分支是否有逻辑漏洞（deadline 计算、计数重置、相位转移遗漏）

## 5. 已知边界与素材状态

- 缺真实失败/断线弹窗帧（XFAIL：fail_recovery_three_frames）——B站视频也无命中，需用户实机录制
- 缺挑战券 0/120 帧（XFAIL：ticket_zero_archaeology）——所有素材均为 120/120
- 原版 1.4 逆向：startChallenge 状态机已借鉴落地（CHALLENGE_START 子状态机 7f1ec4b）
- 龙珠宝物卡视觉特征已采集（蓝框+金球红星+套装X/7，中间槽位）——LONGZHU 重建素材，未实现
- 合成输入有效性未决：全自动路线（驱动级 Interception）等用户批准

## 6. 审查产物要求

1. 中断源清单（代码级出口 × 触发条件 × 实机证据状态 × 建议）
2. 对 5 个初步假设的验证/反驳（证据）
3. 优先级排序的改进建议（防御/诊断/测试），每项含验收标准
4. 特别回答：反复中断的模式性根因是什么？（如果存在）

## 7. 实机录像拆解结论（2026-08-09，双 agent 完成，证据在 C:\tmp\recordings\keyframes\）

### rec1_ingame_boss.mp4（1600x900，632.9s，进游戏→打 Boss→宝物面板常驻结束）
- **选择面板几乎常驻**：211 稀疏帧中 81.5% 有面板，skill/bond/card/treasure 轮换；384-630s 宝物/龙珠面板常驻 207s（含四星球卡）
- **giveUp 误检机理（重要）**：giveUp 模板命中的就是面板底部"放弃"红字按钮 @(800,577±14)。本录像 giveUp 评分 **0.70-0.766 波动（88/211 帧 ≥0.70，从未 ≥0.85）**——而 08-08 ops 实机录像该按钮评分为 0.945。**同一按钮评分在 0.70-0.95 间随渲染抖动** → fail 检测（含 giveUp，阈值 0.85）在"偶尔误触发"状态。bond/card 面板（无放弃按钮）时 giveUp 零命中——方向性证据确凿
- **STAGE_SELECT 误判抖动（新发现）**：局内 16% 帧误判 STAGE_SELECT——右侧任务栏"主线X-Y"文本、Boss 头顶"主线5-X[XX秒]"倒计时、聊天栏命中 stage/stage1-4 数字字形模板。Boss 战段误判密集（300-420s 数十次 0.5s blip）。**局内 context 反复抖动 MAIN_LINE↔STAGE_SELECT，相位机可能被误导回选关**
- 无 UNKNOWN/黑屏/断线/失败弹窗/退出确认——本录像不含中断时刻画面；最接近中断诱因的是常驻面板（giveUp 靠近阈值）

### rec2_postgame_exit.mp4（1586x892，42.5s，战后→退出路线）
- 战后流程：胜利结算（继续游戏@793,615）→ 选关页+存档挑战弹窗 → 时光之穴 Boss（梦魔之王）→ 传家宝挑战弹窗（boss_entry:cjbtiaozhan@0.92-0.93 可检出）→ NPC→弹窗重开 → 克雷什之父战斗 → 顶栏退出 → 确认弹窗 → **点"取消"留在局内（未真正退出回房）**
- **存档挑战弹窗误判 MAIN_LINE**（skillchallenge@0.85）：战后回选关页时弹窗打开 → 脚本可能误入局内逻辑
- **退出确认"确认"按钮无模板**：仅 exit_cancel_btn@0.97（取消）有模板，"确认"无 → 脚本无法完成退出链（回房链缺口）
- cundangInfo@0.92 / damijing@0.88 / hero_refresh_btn@0.85 跨页面命中，不能作为页面区分依据

### 新增审查问题
8. STAGE_SELECT 误判（任务栏/Boss 倒计时文本命中 stage 字形）的实机影响面与压制方案（如"局内锚点存在时压制 STAGE_SELECT"）
9. giveUp/fail 模板评分波动（0.70-0.95）下的 fail 检测可靠性设计（阈值？双锚点？位置约束？）——现有"选择面板存在跳过"是否充分
10. 存档挑战弹窗误判 MAIN_LINE 的防护
11. 退出确认"确认"按钮模板缺失 → 回房链缺口，需要什么证据/方案
12. 423-630s 宝物面板常驻 207s 场景：常驻面板对状态机的影响（品质色循环点击？）
