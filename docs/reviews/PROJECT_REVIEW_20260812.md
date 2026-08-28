# 项目整体评审：技术路线 / Harness / 蓝图 / 可拓展性（2026-08-12）

> 触发背景：8-12 凌晨局内修复（commit `e997b39`）连带弄坏大厅建房/进入链路，上午被迫连发 r10（`de77a19`）、r11（`42f3e95`）两个紧急修复。
> 本文回答：为什么"更新新功能，老功能就崩"，如何根治；技术路线与自我学习闭环怎么优化。
> 证据来源：git 历史取证 + 文档蓝图审查（PROJECT_BLUEPRINT / ARCHITECTURE / NEXT_STAGE 蓝图及评审 / 08-12 交接与基线）+ 代码结构勘察（mediator.py 全量方法/状态盘点）。

---

## 一、回归事故复盘：为什么改局内就崩大厅/商城入口

### 事故链条（可复现的完整证据）

| 时间 | Commit | 内容 |
|------|--------|------|
| 08-12 02:09 | `e997b39` | 名义修局内（进化确认、面板双帧、L1 循环），实际同一 commit 往 `mediator.py` 塞 ~1300 行，**顺手改了大厅侧** `room_start.fallback=null`、建房弹窗蓝色兜底负断言、`_adapt_scales` 排序 |
| 08-12 10:26 | `de77a19` | 紧急修大厅：建房弹窗独立窗口优先 |
| 08-12 11:00 | `42f3e95` | 再修大厅：建房后房间窗口被饿死（r10 trace_20260812_102844） |

### 四个结构性根因

1. **上帝类**：`mediator.py` 约 5887 行、159 个方法、**约 161 个 `self._*` 可变状态**（其中计数器/截止/pending 类约 82 个）。大厅 L0、选关、局内 L1、恢复、战后、秘境全部在同一个 `Mediator` 类。任何局内改动的爆炸半径天然覆盖大厅。
2. **共享判定链**：L0/L1 共用同一个 `_compute_context` 优先级链（选卡锚点 > HUD > 选关页 > 房间 > 建房）与同一套 `match_threshold=0.85`。局内模板/阈值一松，大厅相位就会被"抢走"。`set_phase()` 内有 ~150 行跨阶段状态重置（约 3093–3252 行），漏一个字段即"局内状态污染大厅门闩"。
3. **大杂烩 commit**：局内+大厅+配置+模板混在一个提交里，无法二分定位，只能整包回滚或继续打补丁。
4. **测试是事后回归、不是事前契约**：35 个测试文件多按里程碑（p0a/p1b0/s0/n2）或某次直播事故命名；无 `conftest.py`；没有"改 L1 必跑 L0 契约"的强制机制。

### 附带发现（卡死隐性来源）

- `[input] click CANCELLED: Target window is not foreground`：前台校验 fail-closed 是对的，但取消后**没有重排动作**，直接落入下一轮循环。"半途取消"分支未被状态机显式建模。

---

## 二、防回归方案（按投入产出排序）

### 第 1 层：流程纪律（零代码成本，立即执行）

- **一个 commit 只动一层**（L0 / L1 / vision / config），禁止"顺手改"。
- **发版 gate 脚本**固定串联（工具都已存在，缺的只是强制）：
  1. 全量 `pytest`
  2. 冻结回放 `tools/run_frozen_replay.py`（已有 6 场景）
  3. 大厅 dry-run `tools/diagnose_lobby.py`
- **git tag 管版本**；清理根目录 20+ 个 `build_*` / `dist_*` 目录（版本靠目录名记忆本身就是回归温床）。

### 第 2 层：契约测试（1–2 天）

- 建 `tests/contract/`：把 **平台地图→建房弹窗→房间开始→选关→英雄难度→"开始主线"** 整条 L0 链做成基于真实帧的冻结回放断言。任何人（含 agent）改 `mediator.py` 必跑。
- 每次真机失败后用 `tools/video_breakdown.py` 抽帧固化成新夹具，让每次事故变成永久回归资产（205044 事故已这么做过，应制度化）。

### 第 3 层：结构拆分（一周级，根治）

- `Mediator` 按相位拆为 `lobby_flow.py` / `ingame_flow.py` / `recovery_flow.py`。
- 161 个散状态收敛为 3 个显式 dataclass（`LobbyState` / `InGameState` / `RecoveryState`），相位切换时整体替换而非逐字段重置。
- `_compute_context` 独立成纯函数模块，优先级表写成**数据**（可单测、可 diff）。
- 拆完后"改局内崩大厅"物理上不可能——文件都不同。

---

## 三、技术路线评审

| 层 | 现状 | 评价 |
|---|---|---|
| 模板匹配状态机（主干） | L0/L1 全靠 OpenCV 模板 + 坐标点击 | 与原版 C#（`参考/1.4.1` GameScript.exe：UIAutomation + 模板图库）同路线，验证过可行，**保持** |
| OCR sidecar | 蓝图规定 shadow→分面板灰度，实际已 `OCR=live` | **越级**。自设纠偏门禁（AGENT_CORRECTION_GATES_20260811）禁止 FAIL+waiver 当 PASS，但 skill_recall 正是如此过关。建议退回 shadow，按面板逐个放开 |
| UIA（`l0_uia=disabled`） | 已有完整 `ui/uia/` 模块（~1600 行）未接线 | **大厅层长期方向**：KK 平台是 Win32 窗口，控件树远比模板稳，可根治建房弹窗 HWND 抢占（r10/r11 修的正是这个） |
| 分辨率 | 1600×900 only（SCOPE_OVERRIDE 已定） | 合理，不为 960 分心 |

---

## 四、Harness 与文档管理现状

### 基建强、闸门缺

**已有资产**（超出多数同类项目）：场景回放 harness（`test_scenario_replay.py` + `fixtures/scenarios/*/case.json`，FakeClock/FakeCapture/FakeInputExecutor）、冻结回放、N0/N2 性能基线、S0 安全状态机、OCR 离线评测（O0–O4）、trace jsonl、~28 个工具脚本、~319 张模板。

**缺口**：
1. 没有一条"发版必过"的强制流水线（资产未串联）。
2. 真实断线 / ticket-zero 夹具长期 BLOCKED。
3. 测试未分层（契约 / 回归 / 性能混在一起，无 conftest 共享基建）。

### 文档权威漂移（多 agent 协同的隐患）

- `CURRENT_STATUS_AND_HANDOFF_20260812.md` 顶部写 r11 唯一可测，§1 仍写桌面最新 r7——单文件内版本打架。
- O3 门禁文档保留 FAIL+waiver 叙事，违反自家纠偏规则。
- `ARCHITECTURE.md`（原版 .NET）与 `ARCHITECTURE_20260808.md`（Python）同名不同代；`scenario_harness_design.md` 仍写"设计稿，不实现"但实际已落地。
- **对策**：只维护一份 `CURRENT_STATUS`（每次发版覆盖重写），其余文档一律加"归档，仅供考古"标头。agent 读到过期文档就会做出过期决策。

---

## 五、自我学习闭环优化

现状：真机跑 → 录屏/trace → 人看 + agent 分析 → 改代码 → 打包 → 再跑。可升级为半自动闭环：

1. **失败自动固化为资产**：live run 结束自动收割——从 trace 找 TIMEOUT / CANCELLED / 循环点击段，回放录屏抽对应帧，落 `fixtures/incidents/<date>/` 附 trace 切片。下次修复直接有帧有断言。
2. **证据矩阵自动生成**：`EVIDENCE_MATRIX` 的 18 状态×证据等级目前手填；trace 里已有 phase 转换记录，可脚本生成，保证"哪些链路在当前版本有真机证据"永远新鲜。
3. **模板/词典更新走同一 gate**：新模板入库必须过"正样本命中 + 负样本（空白帧）不命中"双向断言（EVOLVE_TEMPLATE_RECUT 已手工做过 0.98/0.32 验证，纳入 `tools/validate_scenes.py` 强制项）。
4. **Agent 记忆收口**：`docs/agent_shared_logs/INDEX_FOR_AGENTS.md` 为唯一入口；每个 agent 会话结束**必须回写** `CURRENT_STATUS`（改了什么、哪些链路证据失效需重测）。

---

## 六、行动优先级

| # | 事项 | 工作量 | 风险 |
|---|------|--------|------|
| 1 | 发版 gate 脚本 + "一 commit 一层"纪律 + git tag + 清理 build 目录 | 半天 | 零（不动 mediator） |
| 2 | L0 大厅全链冻结回放契约测试（`tests/contract/`） | 1–2 天 | 零（只加测试） |
| 3 | `Mediator` 按相位拆分 + 状态收敛为 dataclass | 一周级 | 中（需契约测试先行护航） |
| 4 | OCR 退回 shadow 按面板灰度；大厅层评估 UIA 接线 | 并行 | 低 |
| 5 | 失败自动固化脚本 + 证据矩阵自动生成 | 持续 | 低 |

> 执行顺序即防回归顺序：先立门（1、2），再动刀（3）。第 3 项动刀前必须有第 2 项护航。
