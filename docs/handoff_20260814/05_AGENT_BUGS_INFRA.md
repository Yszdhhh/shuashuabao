# 板块 5 · Bug 清偿 + 基础架构升级 — 执行 Agent 提示词

> 直接把本文整份复制给执行 agent。层归属：跨层，但**每个 commit 仍只动一层**。
> 先读 `AGENTS.md`（尤其"一个 commit 只动一层"与 C2/C4 红线）、`docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`、`docs/reviews/PROJECT_REVIEW_20260812.md`。

## A. 调试残留清理（第一件事，半小时级）

1. `src/gamescript/mediator.py` 里 **7 处** `debug-5f5f6a.log` 写文件块（`_compute_context` / `_ocr_reward_choice` / `stage_select`×3 / `run`×2，搜 `debug-5f5f6a` 即到），连同 `#region agent log` 一起删除；删根目录 `debug-5f5f6a.log`。这是另一会话的临时观测代码，跑在热路径上每 tick 开文件。
2. 检查 `.gitignore` 是否漏掉 `.pytest_cache/`（git status 里出现了 `nodeids`）。
3. 盘点根目录未跟踪杂项（如 `整夜实验室.bat`）：属测试夹的移去桌面测试夹，属仓库的归位。

## B. 脏工作区分层提交（独占窗口，A 完成后立刻做）

当前约 **126 个未提交文件**横跨所有层。这是二分定位失效的直接风险（e997b39 教训）。执行时**通知其它 agent 暂停写仓库**，按层切 commit，每个 commit 过 `python tools/release_gate.py`：

建议切分顺序（先纯增量、后行为变更）：
1. 夹具与素材（`fixtures/*`、`assets/Images/*` 新增/重裁）——纯证据资产；
2. 知识库配置（`config/game_mechanics_kb.json`、`skill_card_catalog.json`、`skill_card_rarity.json`、`skill_archive_unlocks.json`、`bond_stack_catalog.json`、`official_strategy_defaults.json`、`choice_lexicon.json`、`mode_specs.json` 等）+ 对应一致性测试；
3. 研究文档（`docs/research/*`、handoff 更新）；
4. L1 拿卡行为（choice_policy / mediator 局内 + `tests/test_choice_policy.py`、`test_lab_focus.py`、`test_pick_longrun.py`、`test_skill_combo.py` 等）；
5. L0 选关行为（`selected_stage_row()`、区域判定、冻结回放 `stage_select_scroll` 期望、`tests/test_stage_selector.py`）——**此 commit 内**按流程带 `--reason` 更新 `scene_templates` 快照（131→130，删 `stage_begin_btn`/`startChallenge` 的既定后果）；
6. 模式骨架（`src/gamescript/modes/`、`runtime_status.py`、`tests/test_mode_specs.py`）；
7. 外壳（`desktop_app.py` 改动 + `tests/test_desktop_app.py`）。

注意：A 步删调试代码要么并进第 4 步 L1 commit 之前的独立小 commit，要么单独 commit，别混进行为变更。

## C. 测试债（判断哪边对，再动手）

| 项 | 现状 | 处置 |
|---|---|---|
| `tests/test_hero_mode_temporal.py::test_ordinary_mode_uses_exact_target_and_start_when_row_has_no_highlight` | 红。期望「无高亮也开局」，与现行 fail-closed 相反 | **fail-closed 是对的**（user 已定），改测试期望，归入 B 第 5 步 L0 commit |
| s0 面板可见窗 / temporal 建房窗口闪断 2 红 | 干净 HEAD 上同样红，e997b39 遗留 | 单独修复 commit，先在 HEAD 复现确认根因再改 |
| 提权 5 个真实输入用例 | 非提权 shell 必红（UIPI 硬门禁） | 不改代码；在 `docs/CONTRIBUTING_GATE.md` 写明"需提权 shell 跑"，或加跳过标记（带 reason） |

## D. 实机 Bug（证据先行，每个独立修）

按用户感知的疼痛排序：

1. **换线/第 4 局丢窗**（最高优先）：回房点 KK 开始后 capture `hwnd=None` / 0x0，trace 停在 `ROOM_STARTING`，长测敏捷线因此 0 局（trace `132715` `unhealthy frame timeout`）。修法顺序：先抽帧固化回房后 KK 窗口状态成夹具（`tools/video_breakdown.py`，素材：`20260814_114821.mp4` 尾段 + 长测录屏）→ 写会在修复前失败的窗口重捕获测试 → 再改 `_capture_best`/窗口枚举。**不要没有夹具就猜着改**。
2. **`lab_run` 非 COMPLETE 仍续线**：一条线 0 局也继续跑下一线，浪费整晚。工具层修改（`tools/lab_run.py`），加"本线未完成 N 局则中止序列并显式报错"。
3. **进化 ClickEvolve=0**：夹具里按钮可见但 31 条 trace 进化点击 0 次。轮转修复后 10 号长测若仍为 0，用 `fixtures/longtest_20260814/` 帧写回放测试定位（面板锚点 or 中央像素判定）。
4. **羁绊 OCR 落到 `ocr_bond:slot1/slot2`**：槽位名当卡名点击。加门禁：无规范名的槽位不得作为吞噬/点击对象（fail-closed），回归测试钉住。
5. **选关字模 `1-9` 误读 `1-3`**：fail-closed 会停机不误进，但目标是 1-9 时无法开局。补字模/改判据，`tests/test_stage_selector.py` 加用例。
6. **OCR 致盲后技能全放弃（插队，user 2026-08-15）**：工单 [`05_TICKET_ocr_blind_skill_giveup.md`](05_TICKET_ocr_blind_skill_giveup.md)。录屏 `20260814_234206.mp4` / trace `234214`。worker `spawn`→整局 `disabled`，零卡名，刷 3 次就点放弃。对照 `231455` OCR 活着会选预设。两刀：感知层救 worker；L1 读不到名字禁止放弃技能点。**不是 KB。**

## E. 结构性挂账（本轮不动刀，写清楚留给后续）

- `mediator.py` ~5900 行 / 159 方法 / ~161 共享可变状态：仅登记，不在本板块拆。拆分前置条件是板块 1 的 shell 落地 + RuntimeStatus 替代 print hook。
- 断线场景仍 BLOCKED（缺真机素材），不得用合成帧转正。
- OCR 可移植性（桌面包依赖本机 `.venv-ocr`）维持现状，打包升级另立项。

## 硬边界

- 门禁红了不改快照凑绿；`--update-baseline` 必须带 `--reason` 且先判断哪边对。
- 进房/建房 `fallback` 恒 null（C4）；`INGAME_POLLUTION` 清单随新增局内状态字段同步（C2）。
- D 类每个 bug：先夹具/复现测试，后改码；修复不顺手扩功能。
- B 步进行中，其它板块 agent 不得并行改仓库（可以先写各自的新文件草稿在 handoff 目录外交付）。

## 验收

- `git status --short` 干净（或只剩明确列出的例外）；`git log` 每个 commit 单层、门禁 4/4 PASS。
- D1 丢窗：连跑 4 局不再 `hwnd=None`（真机验证）；D2：0 局线中止并报错；D4：trace 不再出现 `ocr_bond:slot1`。
- 回写 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`：清了什么、哪些链路需重新真机验证。
