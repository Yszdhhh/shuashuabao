# 整合总规划（2026-08-14）— 五板块多 Agent 交接入口

> 本目录是本轮「产品整体化改造」的唯一入口。每个板块一份可直接复制给执行 agent 的提示词：
>
> - `01_AGENT_DASHBOARD.md` — 看板升级（控制中心 P0 落地 + 技能/羁绊/宝物/运行四大板块）
> - `02_AGENT_ATLAS.md` — 图鉴功能（技能+羁绊+等级效果+宝物的只读百科）
> - `03_AGENT_GAME_LOGIC_KB.md` — 底层逻辑库梳理 + 拿卡算法升级
> - `04_AGENT_SELF_LEARNING.md` — 自学习（玩家画像采集 + 建议引擎）
> - `05_AGENT_BUGS_INFRA.md` — Bug 清偿 + 脏工作区分层提交 + 基建
> - `06_AGENT_CLOUD_AUDIT.md` — 云端改动审计（GitHub 上逐 commit 只读审计）
> - `07_AGENT_LAB_VERIFY.md` — Lab 真机验证官（独占真机车道，跑测试夹/读 trace/固化夹具/出验收结论）
> - `08_AGENT_FRAME_BREAKDOWN.md` — 抽帧拆解员**模板**（临时工：检验官填好问题清单+素材路径后一次一单，交证据不下判定）
>
> 硬规矩以仓库根 `AGENTS.md` 为准；实机现状以 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md` 顶部为准。
> 第四节的 7 项拍板由用户给出结论后，由整合方回填到对应板块提示词，执行 agent 只拿无歧义版本。

## 一、四条工作线现状综合（2026-08-14 14:00 快照）

| 线 | 干了什么 | 落点 | 卡在哪 |
|---|---|---|---|
| 竞品/模式/蹭车线 | 竞品静态拆解 → ModeSpec 骨架（跟车/赌木/站团本/蹭车全 `live_enabled=false`）→ 蹭车录像夹具 + 测试夹找房可跑线（dry/live）→ 控制中心+宠物+图鉴对抗终稿 + 看板整合简报 | `config/mode_specs.json`、`fixtures/lobby_hitch_*`、`docs/research/CONTROL_CENTER_PET_ATLAS_PLAN_20260814.md`、`DASHBOARD_INTEGRATION_BRIEF_20260814.md` | **方案已定、外壳零实现**（无 `src/gamescript/shell/`）；找房缺行/搜索/刷新锚点；主工程不接点击 |
| 拿卡算法线 | 官方 7 页说明入库 → 资源账本纠正（G 技能点优先/白绿先刷/目录稀有度压 OCR/审判单向排斥）→ 03c 真机复验过（轮转/1-8/智力链）→ 循环修复（羁绊后转宝物→进化→黑商）→ 08/10 长测脚本 | `config/game_mechanics_kb.json`、`choice_policy` 改动、`测试夹\08/10-*.bat` | 进化点击 0 次；黑商证据刚起步；KB 大部分 `wired_to_decision=false` |
| 选关/羁绊收紧线 | L0 选关高亮 fail-closed（无高亮不开局、3 次停机）→ 羁绊吞噬需勾选/已开摞守卫 → 真机对照选关已稳 | `selected_stage_row()`、`choice_policy` 吞噬规则、`fixtures/stage_select_20260814/` | 留下 `debug-5f5f6a.log` 热路径残留（7 处）；换线丢窗未修 |
| 长测拆解线 | 三线长测 trace+录屏只读拆解：SELECT 无「白先紫」实锤；根因=稀有度目录空洞 + conf 连坐稀有度；产出长测夹具与扫描工具 | `fixtures/longtest_20260814/`、`tools/scan_longtest_traces.py` | `skill_card_rarity.json` 缺剑气/陨石/地震/普攻/奥术树；`lab_run` 非 COMPLETE 仍续线；敏捷线丢窗 0 局 |

## 二、收敛后的核心问题（按疼痛排序）

1. **外壳是最大欠账**：方案三份文档全齐，代码零行。看板升级（板块 1）就是把它落地，其余板块的 UI 交付都压在它上面。
2. **换线/第 4 局丢窗**（`hwnd=None`，ROOM_STARTING 后）：长测被腰斩的第一杀手 → 板块 5 D1。
3. **稀有度目录覆盖不足 + conf 连坐**：「目录压 OCR」在主流卡上形同死代码 → 板块 3 B1。
4. **126 个脏文件跨层堆积**：二分定位已失效，必须先分层提交 → 板块 5 B（独占窗口）。
5. **知识分散**：官方 KB / 卡目录 / 等级库 / 张数目录 / 策略包六处，各自权威但没有总索引 → 板块 3 A；对用户的展现层缺失 → 板块 2。
6. **木头阈值、抽卡不足烧刷新**等已定未接的账 → 板块 3 B2/B3。
7. **进化 0 点击、羁绊 slot 名误点、lab 续跑** → 板块 5 D2–D4。
8. **自学习尚无采集通道**（存档等级靠手填、TAB 属性完全没有）→ 板块 4。

## 三、执行顺序与并行规则（关键，安排 agent 时照此排班）

```text
第 0 步（独占仓库，其他人只读）
  板块5-A 清调试残留 → 板块5-B 脏工作区分层提交（7 个 commit，每个过 gate）

第 1 批（可并行，互不碰文件）
  板块1  shell P0（外壳层：src/gamescript/shell/ + desktop_app 瘦身）
  板块3-A 逻辑库总索引（纯文档）
  板块2-第1步 AtlasView 数据层 + 一致性测试（不依赖 shell）
  板块4-P0 画像采集器（新模块 + 测试夹入口）

第 2 批（有依赖/需串行）
  板块3-B 算法接线（L1）  ←→  板块5-D3/D4（也是 L1）：同层串行，一次只开一个会话
  板块5-D1 丢窗修复：先抽帧固化夹具，可与 L1 工作并行（动的是窗口捕获层）
  板块2-第2步 图鉴 UI、板块4-P2 建议卡片：等板块1 P0 合入后再开
  板块1 P1（RuntimeStatus+宠物）：P0 验收后

真机互斥：同一时间只跑一个测试夹 bat；10 号长测、09 找房、08 抽帧不同时；
看板 LIVE 与 lab CLI 不同时（live.lock）。
```

跨板块红线（所有 agent 通用）：
- 任何 `live_enabled=false` 的模式不得改 true；C4 进房/建房禁颜色兜底；合成帧不冒充实机证据；不确定 fail-closed。
- 一个 commit 只动一层；提交前 `python tools/release_gate.py` 退出码 0；门禁红了不改快照凑绿。
- 改了行为就回写 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`。

## 四、7 项已拍板（user 2026-08-14 14:55，结论已回填各板块提示词）

| # | 拍板结论 | 落到哪 |
|---|---|---|
| 1 | 特殊房**无「锁定」按钮**；按钮字与操控与普通房一致、仅颜色不同（金/蓝）。识别以按钮**文字**（准备/已准备/取消准备）为主锚，颜色只作辅助，金蓝两套模板都收 | 板块 1 蹭车卡文案；未来 lobby_hitch 接线 |
| 2 | `hitch_reject_list` 反选编辑器 **P0 不露出**，字段保留在 ModeSpec | 板块 1 |
| 3 | 蹭车只做 **3/4 前缀模糊搜索**；精确关卡过滤与房间名识别留作后续拓展，UI 隐藏该字段或标「后续拓展」 | 板块 1；找房专项 |
| 4 | **F1=操作切回自身英雄**（防 G/V/F 面板无法操作）；**F2=回基地**（视角偏离或要点秘境/传家宝点不到时）。此前口述记忆有误，以本条为准 | 板块 3 入库 KB；蹭车流程文案更正 |
| 5 | 桌面英雄用**魔兽英雄形象做小改动**处理。仅本机工具内使用、不对外分发；穿透/不可点等安全要求不变 | 板块 1 P1 宠物素材 |
| 6 | 蹭车分两阶段：**先把找房链做好，再完善局内动作**；现有骨架规则已较完善，全部保存不动 | 找房专项排期 |
| 7 | TAB **纯查看无副作用**，可放心采集；并新增需求：基于个人属性+特性做一个「**个人画像简要看板**」 | 板块 4（P0 放行 + P2 新增看板卡片） |

## 五、Agent 启动排班表（每个 agent 开工时照此启动）

| Agent | 环境 | 启动必读（按序） | 主要工作 | 批次 | 侧重提醒 |
|---|---|---|---|---|---|
| **Infra**（板块 5） | 本地 | `AGENTS.md` → `05_TICKET_ocr_blind_skill_giveup.md` → `05_AGENT_BUGS_INFRA.md` | **插队** OCR 致盲+技能误放弃（先 InfraB 再同步 Local）；其余仍是 A/B 与 D1 | 插队优先于 D1 | 13 号跑 InfraB；两刀两 commit；不是 KB |
| **Shell**（板块 1） | 本地 | `AGENTS.md` → `01_TICKET_lab_reads_dashboard.md` → `01_AGENT_DASHBOARD.md` | **先做**测试 bat 读 `user_settings.json`（技能/关卡/英雄模式）；再做 shell P0 + 四大板块 | 第 1 批插队 | 只动外壳 + `tools/lab_run.py` + 13 号 bat；不碰 mediator；Local/InfraB 各改一份 lab_run |
| **KB**（板块 3） | 本地 | `AGENTS.md` → `03_AGENT_GAME_LOGIC_KB.md` → `OFFICIAL_GAME_MECHANICS_KB_20260814.md` | 先 A 逻辑库总索引（纯文档，第 1 批）；再 B 算法接线（L1，第 2 批） | 索引第 1 批 / 接线第 2 批 | **L1 车道与 Infra-D3/D4 串行**，开工前互相确认 |
| **Atlas**（板块 2） | 本地 | `AGENTS.md` → `02_AGENT_ATLAS.md` → `CONTROL_CENTER_PET_ATLAS_PLAN_20260814.md` §7 | 第 1 步 AtlasView join + 一致性测试（第 1 批）；第 2 步图鉴 UI（等 Shell P0） | 数据层第 1 批 / UI 第 2 批 | 禁止第四份卡名表；默认只读 |
| **Profile**（板块 4） | 本地 | `AGENTS.md` → `04_AGENT_SELF_LEARNING.md` | P0 画像采集器（存档技能等级 + TAB 属性，只读）；P1 建议引擎；P2 看板卡片（等 Shell P0） | P0/P1 第 1 批 / P2 第 2 批 | 采集零点击风险；画像不进仓库配置 |
| **Audit**（板块 6） | **云端** | `AGENTS.md` → `06_AGENT_CLOUD_AUDIT.md` → `CONTRIBUTING_GATE.md` | 每次本地 push 后逐 commit 审计：分层纯度、红线、快照篡改、契约同步、卫生；出报告 | 常驻，push 触发 | 只读 + 报告分支；云端测试数不作基线 |
| **LabVerify**（板块 7） | 本地 | `AGENTS.md` → 交接文档顶部 → `07_AGENT_LAB_VERIFY.md` | 独占真机车道：指挥跑测试夹 bat、自读 trace/incidents、逐判据出过/不过结论、bug 派单给板块 3/5；重录屏拆解**派单给拆解员**（08 模板），自己只判定 | 常驻，各板块交付后验收 | **不修代码**；只出证据与结论；一次一个 bat |
| **拆解员**（板块 8） | 本地·**临时** | 由检验官填好 08 模板占位符后新开会话 | 按问题清单抽帧找画面、对 trace 行号、固化夹具、交「问题→证据」表；不下判定 | 按单触发，可与真机跑并行 | 一次一单用完即弃；只读+新增夹具；不占真机车道 |

**Git 节奏（全体遵守）**：本地每个板块的大功能完成 → 分层 commit（一层一个）→ `python tools/release_gate.py` 退出码 0 → push `origin`（当前工作分支 `trial-merge`）→ 通知 Audit agent 审计该 commit 范围 → 用户看审计报告决定继续/返工。审计 FAIL 的 commit 由对应板块 agent 领回修，不由 Audit 改。

**真机车道（同一时间只占一个）**：测试夹 bat（10 长测 / 09 找房 / 08 抽帧）互斥；看板 LIVE 与 lab CLI 互斥（live.lock）；Profile-P0 的采集 bat 也走这条车道排队。**车道由 LabVerify（板块 7）统一调度**：各板块要真机验收，把判据清单交给它，不自己抢跑。

## 六、整合角色（本会话）保留的工作

- 维护本目录与各板块提示词的一致性；板块间接口变化（如 shell 包名、AtlasView 结构、profile JSON schema）由整合方仲裁。
- 板块 5-B 分层提交的 commit 切分评审（哪个文件归哪层拿不准时来问）。
- `mediator.py` 巨石拆分的时机判断（前置条件：shell P0 + RuntimeStatus 替代 print hook 完成后另立项）。

## 七、总控日常调度节奏（2026-08-16）

### 7.1 四种触发方式

| 类型 | 角色 | 怎么触发 | 收口方式 |
|---|---|---|---|
| 常驻循环 | LabVerify + 按单拆解员/OMP | 用户给下一轮可证伪判据；LabVerify 排真机，长录像派 08 | LabVerify 每轮自己提交纯 `fixtures/` 感知/素材 commit；拆解员不改 config/策略 |
| 攒批处理 | KB、Infra | 同一车道积累 2–3 张单后开一次会话 | 一张单/一层一个 commit；可合并成一张真机验收矩阵，但不得混层 commit |
| 主动排期 | Shell、Atlas、Profile | 每 1–2 天固定推进一个产品交付，不等待真机循环“自然产生需求” | 独立 worktree；Shell 接口先行，Atlas/Profile UI 等 Shell 稳定 |
| push 自动触发 | Audit | 每次 push 提供明确起止 SHA | 只读审计报告；FAIL 退回原板块，不由 Audit 修 |

### 7.2 “攒批”不是“混层”

- KB 可以在一次会话清 2–3 张 L1 策略单，例如稀有度补洞、conf 解耦、刷新账本接线；每条仍独立 commit/测试。
- Infra 只按同层攒批：进化 0 点击 + slot 误点都属 L1，可同会话串行；丢窗属于捕获/恢复，选关字模属于 L0/感知，必须另 commit，必要时另会话。
- KB 和 Infra 共用 L1 单车道，不能同时改 `choice_policy.py` 或 `mediator.py` 局内段。
- 可以把若干已过 gate 的候选 commit 组成一次 LabVerify 验收矩阵，减少烧局；任何一项未触发仍写“未触发”。

### 7.3 日常证据循环的收尾责任

```text
LabVerify 定判据
  → 用户只跑一个 bat
  → LabVerify 读 trace/incidents
  → 长录像派给拆解员
  → 拆解员交问题→证据表
  → LabVerify 判定过/不过/未触发
  → LabVerify 固化/验收 fixtures
  → 单独 fixtures commit + gate
  → bug 单派给 KB 或 Infra
```

拆解员只拥有证据目录；`config/game_mechanics_kb.json`、策略表和算法接线必须交回 KB。这样 Infra 不再周期性替日常循环“打扫夹具”，只在真正跨层脏树或基础设施故障时出场。

### 7.4 2026-08-16 OMP 全量抽帧收口

- 原始录像：`G:\测试视频+抽帧\录屏素材`，48 个视频，约 23.494 GB。
- 历史抽帧：`G:\测试视频+抽帧\tmp_archive`，约 26.30 GB；活动临时目录：`G:\测试视频+抽帧\treasure_temp`。
- OCR 模型保留：`C:\tmp\ocr_model`，不要为“全搬 G 盘”破坏已验证的 ASCII 模型路径。
- 已同步夹具：`fixtures/treasure_merchant_dragonballs_20260815/`，213 文件，其中 `cards/` 196、`tooltips/` 14，两个索引 JSON 均可解析。
- 已覆盖：刀刀大圣、异火兵主、`20260815_013304` 精抽；`134529` 证伪桌面聊天误报；其余 8 段粗扫按命中结果入证据。
- 已确认：黑市刷新 60、每 180 秒 1 次免费刷新、折扣/货架画面、龙珠套装角标表示已收集数、贪欲之刃与玻璃大炮的负面事实。
- 未决：七星球木材奖励存在 `+10000` 与 `+100` 两段真机 OCR，两读并存；一星球、六星球、7/7 神龙许愿界面仍无证据。KB 不得选一个数字覆盖另一个，也不得据此自动接策略。

### 7.5 当前必须先做的脏树收口

2026-08-16 新主仓库实际为 74 条状态记录（28 modified、46 untracked，未 staged），不是旧汇报里的 29。总控先冻结主树写入，再让 Infra 以“只分层、不改内容”的整合身份切分：

1. OMP `fixtures/` 感知/素材；
2. KB 配置与研究索引；
3. Atlas 新模块与测试；
4. Profile 新模块、工具与测试；
5. Shell/外壳；
6. L1 行为；
7. L0/感知；
8. 迁移路径与交接文档。

每层独立 commit、独立 `python tools/release_gate.py`；拿不准归属就停下来问，禁止再次形成“一个大 commit 全收”。
