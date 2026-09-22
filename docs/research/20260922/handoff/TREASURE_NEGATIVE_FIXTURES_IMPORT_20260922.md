【刷刷宝 · 宝物负面卡夹具入库 + 诅咒之力/提高上限默认不拿 · 2026-09-22】用中文。

## 0. 身份与边界
- 你是唯一做这件事的 agent，但不是唯一在仓库工作的人：不覆盖、不还原他人文件。
- 主目录 G:\刷刷宝\GameScript-Local 是实机测试运行目录，**禁止在主目录改文件**。
- 从主目录 HEAD 新建 worktree：
  git -C G:\刷刷宝\GameScript-Local worktree add G:\刷刷宝\Worktrees\treasure-negative-20260922 -b fix/treasure-negative-fixtures-20260922 afc3443f2a7862c2fb2e2f68692f203fa7a25d02
  开工前核对 HEAD = afc3443f2a7862c2fb2e2f68692f203fa7a25d02。
- 先读：G:\刷刷宝\GameScript-Local\AGENTS.md。
- 不启动游戏、不发输入、不跑全量门禁（release_gate.py 由主架构合并后独占跑）、不打包、不动桌面快捷方式和 current.json。
- **不改 ui-v2/index.html**（UI-22 是唯一参考，SHA 受控）。

## 1. 输入（全部真机原帧，禁止合成/替代）
- 13 张卡原帧（每卡 1–2 张 jpg，1600×900 面板）：
  G:\刷刷宝\_facts_20260922\treasure_debuff_frames\<卡名>\panel_*.jpg
  卡：力之极、命运骰子、恶魔契约、提高上限、敏之极、智之极、木材梭哈、混乱转换、玻璃大炮、登神长阶、经验压制、贪婪契约、金币梭哈
- 说明：同目录 report.md（取证过程、patterns 缺口）与 treasure_catalog.md（96 卡 OCR 描述原文 + verdict：负面19/存疑2/正面42/套装33）。
- 诅咒之力真机图（不在上面目录）：
  C:\Users\10639\AppData\Roaming\LarkShell\sdk_storage\2fb38f2e7af030f12d6b7d4976252c48\resources\images\img_v3_0215p_31b47da6-e1bd-412f-91f3-84feecf3958g.jpg
  （1600×900；卡面：造成的所有伤害×1.75，自身受到诅咒，恢复效果 -99%，护甲 -10000）
- 搁置补丁（参考，不直接 git apply）：
  C:\Users\10639\AppData\Local\Temp\claude\C--Users-10639\27d14b82-7af8-446a-ab36-3527f5c26be4\scratchpad\other_agent_fix_backup\treasure_default_skip.patch
  它涉及 config/choice_lexicon.json、config/choice_policy.json、config/dashboard_mechanics.json、src/shuabao/choice_policy.py、src/shuabao/shell/main_window.py、tests/contract/test_choice_semantics_contract.py、tests/test_card_template_bidirectional.py、ui-v2/index.html。
  **只移植除 ui-v2/index.html 以外的部分**；若 main_window.py/UI 侧改动离不开 index.html，停下来报告，不自行改 UI。
  补丁里“效果待实机采集 / live-capture-pending”这类文字，按本次真机帧改成真实卡面描述和证据路径。

## 2. 要做的事（两件，分两个 commit）

### Commit A：夹具入库（纯数据，不改行为）
1. 按现有格式把 14 张卡（13 + 诅咒之力）入库到 fixtures/treasure_negative/<卡名>/：
   - panel_*.png：原帧转 PNG（无损转码，不裁剪不缩放不增强）；文件名保留原时间戳后缀。
   - name_*/desc2_*：按现有 6 张卡的 ROI 规则裁剪（参考 fixtures/treasure_negative/README.md 与 _panels/treasure_panel.png）；裁不准就只放 panel，不硬凑。
   - 同一原帧含多张目标卡（如 panel_030308_666 同时在 力之极/混乱转换，panel_185040_112 同时在 提高上限/经验压制）时，各卡目录各放一份并在 INDEX 标注槽位。
2. 更新 INDEX.json（names + entries）与 DESCRIPTIONS.json（description 取整帧可见原文，逐字核对 treasure_catalog.md 的 OCR，冲突以肉眼看图为准并注明；evidence 路径；pattern_hints）。
3. README.md 的“已确认 N 张”与目录表同步。
4. 每张入库图记录 SHA-256 与原始来源路径（写进 INDEX 或单独 SOURCES.json），可追溯到 _facts 目录原件。

### Commit B：诅咒之力 / 提高上限 默认不拿（Owner 已批准的仅这两张）
1. 按搁置补丁把这两张加入 DEFAULT_NEGATIVE_NAMES（choice_policy.py）、config/choice_policy.json negative_names、choice_lexicon.json、dashboard_mechanics.json；dashboard 文案用真实卡面描述，evidence 指向刚入库的 panel。
2. 其余 12 张（及 treasure_catalog 负面19/存疑2 中未入名单的）**只入夹具、不改默认拿/不拿**。原因：Owner 只批准了诅咒之力/提高上限；其余是否默认禁拿待 Owner 逐卡裁决。
3. negative_patterns 缺口（report.md §6 所列：恶魔契约“无法再升级”、命运骰子“增幅-15%”、登神长阶“全属性-35%”、玻璃大炮“受到的所有伤害提高”、三极“扣除”、梭哈“清0”、经验压制“经验-70%”、诅咒之力“恢复效果-/护甲-”）：
   **本轮不改 patterns**（patterns 一改就会让这些卡在生产里变成不拿，等同于替 Owner 拍板）。只在 test_treasure_negative_fixtures_contract.py 的“当前缺口”断言里如实列出，并在交付里给出拟议 pattern 清单供 Owner 裁决。

## 3. 测试
- 契约测试要能覆盖新卡：每张入库卡 ≥1 张真机 panel；诅咒之力、提高上限走名字路径 is_negative_treasure=True、真机面板端到端 choose_action 不选；其他 12 张断言其当前实际行为（命中/未命中），不改期望去迎合。
- 不许用 skip/xfail、改 GATE_BASELINE 或删断言放行。
- 运行（worktree 内，主目录 .venv 解释器）：
  G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe -m pytest tests/contract tests/test_choice_policy.py tests/test_p1_choice_fsm_contracts.py tests/test_card_template_bidirectional.py -q
- 若 scene_templates / asset manifest 类测试因新增文件报 asset 清单不一致：fixtures 不应进 assets 清单，先查原因并报告，不要为此改 asset 快照。
- git diff --check 无输出。

## 4. 交付（回传给主架构）
- worktree 路径、分支、两个 commit SHA、各自 diff stat。
- 入库卡数/帧数表：卡名 | panel 数 | 裁剪数 | 描述原文 | 来源 SHA-256。
- 测试命令与结果数字（passed/failed/skipped），exit code。
- 拟议 negative_patterns 清单（逐条：pattern | 会命中的卡 | 误伤风险 | 是否建议），标“待 Owner 裁决”。
- 未能完成项与原因，UNKNOWN 就写 UNKNOWN。
- 不 push、不合并到主目录；合并与全量门禁由主架构做。完成即收工，不扩展到宝物策略/黑商/羁绊。
