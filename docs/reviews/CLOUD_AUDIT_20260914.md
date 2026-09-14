# ShuaBao 云端架构审计 — 2026-09-14

审计基线：`main@b348da79d85cc5673a8a7629ff5b176f5eadba8a`（PR #21 merge commit）  
审计范围：`b4cf93f..b348da7` + 当前发布链 / 订阅服务并行线 / 上一轮云端审计  
审计性质：只读；除本报告外未修改代码、测试、夹具、baseline、构建产物或 Git 历史；未开 PR、未合并。  
证据纪律：pytest、离线真实帧 replay、click success 均不升级为实机 PASS；仓库外 `%TEMP%\shuabao-captures\...` bundle 云端不可见时只记“需本地提供”。

---

## 1. 结论

### 1.1 单人 `mode_id=normal_farm` 长程测试：**NO-GO（针对无人值守/验收性质长程）**

当前可以做**短时、有人看守的诊断 smoke**，但不建议直接恢复“放着跑”的长程验收。主因不是当前 63d351d 的传家宝修复本身，而是**大量通用恢复语义仍被 `_passenger_mode()` / `_hitch_enabled()` 锁在蹭车路径**：相同的暂停、胜利页、战后面板、退出确认异常，蹭车会重置预算继续观察，`normal_farm` 仍 `Phase.ERROR + stop()`。这会把长程测试变成“哪次 UI 抖一下就整段运行结束”，无法检验真正的长程稳定性。

**转为 GO 的前置条件：**

1. 把“无人值守恢复能力”从 `_passenger_mode()` 业务语义中抽出来，例如新增 `_unattended_recovery_enabled()`，至少覆盖 `normal_farm / lobby_hitch / follow_team`，仅迁移通用恢复，不复制蹭车业务规则。
2. 修掉 B 节列出的单人整机停机点：暂停恢复、胜利页/继续游戏、意外存档页/挑战广场、存档/传家宝关闭失败、未实现战后页、未验证 archive、继续游戏后转场、QUIT/NEXT 退出链。
3. Owner 明确**单人传家宝后的业务规则**（是否等真实 Victory、何时退出、秘境/团本如何收口）。蹭车的“60 秒/已获取装备就退”不能直接复制。
4. 63d351d 的传家宝入口/顶栏修复至少做一轮当前候选 SHA 的实机回归；若同时做 A1 建议的阈值/OCR 兜底，则以新 SHA 重验。
5. 为上述每个恢复分支补 `normal_farm` 测试；完整 `release_gate` 通过后，再做当前 SHA 的短 smoke → 多局长程。长程证据必须保留真实业务后置条件 bundle。
6. 重新跑一次 exact candidate 的 GitHub Actions：PR #21 head `6ded7ff` 的 CI 成功，且它和 merge commit 的 tree 都是 `ec59fbce...`；但 `main@b348da7` 自己的 push run #190 是 **failure，runner_id=0、steps=[]**，说明 exact merge SHA 没真正执行 CI。这个更像 runner/工作流执行层失败而非测试失败，但不能写成“main CI 绿”。

**当前单人验证等级：**

- `config/mode_specs.json:5-29` 自己仍标 `normal_farm.evidence_status = live_partial`。
- `config/mode_evidence.json:5` 明确是 `MISSING`：“当前 SHA 尚未绑定完整实机证据”。
- `docs/handoff_20260914/ARCHITECTURE_STATUS_20260914.md:40-58` 的本轮实机表主要是蹭车；63d351d 传家宝仍为“离线真实帧重放，待实机”。
- `tests/test_b15da05_real_regressions.py:82-109` 有默认 `Settings(...)`（即 `normal_farm`）对真实存档帧的离线回归，证明一个冷启动存档场景不 ERROR；但同文件大量新链路测试明确构造 `lobby_hitch`。这是有价值的离线覆盖，不是当前 SHA 单人实机 PASS。
- 上一轮 `docs/reviews/package_20260913/RELEASE_PROGRESS_ASSESSMENT_20260913.md:58-66` 已把“刷图/带队战后 fail-closed”列为未完成准备工作；本轮代码仍可见这些分支。

### 1.2 `external-beta`：**NO-GO**

即使后续单人长程没有大问题，当前也不能直接外发。存在多项**代码硬门**：

| 阻塞项 | 当前状态 | 是否外发前必须解决 | Owner |
|---|---|---:|---|
| 外发模式真机证据 | `build_release.ps1:250-304` 强制所有 `live_enabled && desktop_start` 模式当前 SHA `PASS`；`config/mode_evidence.json:4-9` 中 `normal_farm / follow_team / lobby_hitch` 全是 `MISSING` | **必须** | 本地 + Owner（范围） |
| 固定 HTTPS 订阅域名 | 源码默认仍是失效/旋转 Quick Tunnel；production-hardening 的固定域名仍只是 runbook | **必须** | Owner + VPS |
| `--strict-release` | `disconnect_modal_missing = BLOCKED`；外发构建自动加 strict | **必须** | 本地（采集）+ 云端（验收） |
| Authenticode + manifest 签名 | 外发脚本要求真实证书私钥、timestamp、signtool；所有 frozen 还要求 Ed25519 manifest key/registry | **必须** | Owner / 构建机 |
| PR #20 DOM/XSS 转义 | main 仍保留动态 `innerHTML` sink；PR 已有针对性修复与恶意 payload 测试，但 Draft 且落后 main | **必须** | 云端/执行 agent |
| 订阅 production-hardening 实际部署验收 | 专用 production compose 已存在，但仓库证据明确写“未切生产流量”；固定 hostname 未落地 | **必须** | VPS |
| 当前候选 exact-SHA CI | PR head tree 通过；merge SHA 的 push run #190 未真正启动 runner | **外发前必须** | 云端/Owner |
| GATE baseline 正规再生 | 当前 baseline 是针对性手改，违背工具规定的全阶段 update 流程 | **外发前建议视作必须清账** | 本地 |
| 账号层 `feat/account-layer-20260913` | 分支存在、最新 `cdf9603`；上一轮明确属于 0.5，不进 0.4 | **不是 0.4 阻塞**，除非 Owner 改范围 | Owner |
| 旧 Boss layering 分支 | `1b311b3` 与 main 已 diverge，且改同一片 Boss 代码 | **不是发布阻塞**；不要直接合 | 云端 |

注意：外发模式证据门比“单人长程通过”更严格。`config/mode_specs.json` 当前把 `normal_farm`、`follow_team`、`lobby_hitch` 都设为 `live_enabled=true && desktop_start=true`；因此只把单人跑绿仍会被 `Assert-ExternalModeEvidence` 拒绝。若 Owner 决定 0.4 external-beta 不开放某个模式，应通过正常 PR 明确收窄 `mode_specs` 产品范围并重跑契约，而不是把没有实机证据的模式硬写成 PASS。

---

## 2. A — `b4cf93f..b348da7` 改动正确性

### A1 — **P1** / `src/shuabao/mediator.py:6507-6544` / 传家宝入口仍是模板单点感知

**代码事实：** `_find_post_game_hub_entry()` 对 heirloom 仅用 `chuanjiabao / chuanjiabao_thin / cjbtiaozhan` 做灰度归一化互相关，多尺度、固定 `threshold=0.58`、固定 ROI。`src/shuabao/vision/ocr_shadow/client.py` 的 OCR 接口只识别调用方提供的 bbox，不承担文本检测。

**失败场景：** 这次 P0 已证明“悬停粗体/非悬停细体”就足以让模板从真实命中掉到 0.45–0.57；客户端换字体、DPI/分辨率、抗锯齿或 UI 更新后仍可能再次 miss。更危险的是已知粗体 `传家宝` 模板在“存档挑战”上能到 **0.573**，离 0.58 只有 0.007。

**建议修法：**

1. heirloom 模板阈值提高到 **0.70** 是合理的第一层收紧：当前已有真实正样本 ≥0.83，已知错位/异词 ≤0.573，0.70 给出明显 margin；阈值要用现有真实夹具回归后落地。
2. 同时补**受限 OCR fallback**，不要做全屏 OCR：仅在 `_post_game_pending` 的 heirloom 路由、`_top_bar_mode(frame)=="plaza"`（最好再叠加左上 quit / 广场锚点）且所有模板 miss 时，裁标签 ROI → 白字阈值化 → 连通域切字并合并为词框 → 逐框喂给现有 OCR → 高置信命中“传家宝”后，按受约束的标签下方 offset 点击。建议至少连续两帧稳定词框/文本再授权点击。
3. OCR fallback 只负责**检测+验证文字**，不能把 OCR 文本本身扩展成任意坐标点击 authority；点击仍必须落在 heirloom ROI/几何约束内。

**是否阻塞单人长程：** **条件阻塞**（单人启用 `cjb_boss`/走传家宝链时阻塞；否则至少要求 63d351d current-SHA 实机回归）。  
**是否阻塞外发：** **是**。这是刚刚连续两轮漏过的真实 P0 根因类别，外发前不宜只靠再加一张模板。

### A2 — **P2** / `src/shuabao/mediator.py:6781-6800, 14810-14835, 15505-15530` / 顶栏否决把“plaza/raid”当绝对反证

**代码事实：** 两处 stage-page guard 都要求 `_top_bar_mode(frame) is None`；因此识别到 `存档`（plaza）或 `团本`（raid）时，即使 `_find_stage_page(frame)` 命中，也不会进入 STAGE_SELECT/误开页退出。现有本地审计在 1400+ 已有帧里看到：真正选关页顶栏无模式标签，f0353/f0707 的“存档 + stage”都是广场误报，这证明本次修复对**已见样本**正确。

**待核实风险：** 仓库里没有证明“真实选关 overlay 一定遮掉顶栏”。如果在广场/团本里确实打开了一个选关层，而顶栏仍留在背后，当前绝对否决会把真实选关页卡成 MAIN_LINE 零输入。该场景目前没有实机样本，不能宣称已安全覆盖。

**建议修法：** 把顶栏降为“否决弱 stage 证据”，而不是绝对否决：例如 `topbar=plaza/raid + 已确认广场锚点` 时否决；若有更强的选关页专属锚点/几何/关闭按钮，则允许强证据覆盖。至少补“广场/团本上真实打开选关层”的 Ground Truth 后再定策略。

**是否阻塞单人长程：** **建议长程前补强或至少定向 smoke**；非绝对 P0。  
**是否阻塞外发：** **是，需闭环或提供实机反证**。

### A3 — **P2** / `src/shuabao/mediator.py:3606-3668` / b66f1ce 宝物兜底会在首次 transient miss 时盲选第 1 格

**代码事实：** 该逻辑仅在 `_passenger_mode() && kind=="treasure"`。当 `can_refresh` 为 false、没有有效 OCR 名称时，代码 `candidates = candidates or list(slots)`，最后可直接选择第一个槽位；它并不要求“已确认刷新预算耗尽”。因此**第一次打开面板**如果刷新按钮只是本帧没识别到，就可能立即盲选 slot 1。

**评价：** “推进流程优先于卡牌质量”作为蹭车末段业务策略可以接受；但“一个刷新按钮检测 miss = 已到末段”太激进。面板本身和槽位已被确认，所以不是随机点屏幕；风险在于语义上可能拿到负面卡。

**建议修法：** 只有在“刷新预算明确耗尽”或“同一物理面板指纹连续 2 帧都确认无刷新能力”后才允许末段 slot fallback。OCR 无名时先做一次有界 re-observe；仍无名且已证实末段，再按 Owner 已接受的“任意一格推进”策略选第 1 格。

**是否阻塞单人长程：** **否**（passenger-only）。  
**是否阻塞外发：** **如果 external-beta 包含 lobby_hitch，则应修；否则不阻塞 normal_farm**。

### A4 — **P3 / 待核实** / `src/shuabao/mediator.py:4047-4072, 4115-4185, 4230-4255` / 去掉杀敌余额门槛后 V 频率与聊天条的因果仍未建立

**代码事实：** 蹭车 L1 环是 `merchant → treasure → pickup → public_bag`；V 异常 episode 到上限后 8 秒可重置再探测，不再由黑商杀敌余额长期阻断。开 V 实际走 HUD `act_click(...)`，不是直接发送键盘 `V`。另有物理面板指纹防重复点击和 episode/cooldown 边界。

**实机已有现象：** 本地审计记载第二局约 450 秒里开 V 13 次、选中 7 次，没有观察到失控刷屏；但聊天条几乎全程打开。因为开 V 是 HUD 点击，当前代码证据**不能证明**“V 重试导致聊天条打开”，也不能排除游戏的“次数不足”提示或其他输入侧效应。

**建议修法：** 下一轮 bundle 记录时间序列：`OpenTreasurePanel`、`panel absent/次数不足`、chat-open 首帧、关闭 chat 行为；只有相关性成立再改。若确认是 V 侧效应，优先在 V 请求前做 chat-focus/overlay 检测并安全收口，而不是恢复错误的杀敌余额门槛。

**是否阻塞单人长程：** **否**（本轮变化集中 passenger）。  
**是否阻塞外发：** **单独不构成硬阻塞；lobby_hitch 外发前应有实机结论**。

### A5 — **P3** / `src/shuabao/mediator.py:6200-6465, 6990-7205` / Boss 注释与实际 fallback layering 不一致，但业务行为符合用户规则

**代码事实：** WAIT/定位预算耗尽后会进入 `_handle_boss_anomaly_retry_or_skip`；该 handler 会宽尺度寻找**当前可识别的最后一张卡**并点击，即使之前没有“已到底”证据。若一张卡都认不出，则记录 incident 后跳过；没有把整机停掉。

**结论：** 实际行为符合用户规则：“目标找不到 → 点能点到的最后一张；一张都认不出 → 跳过；任何 Boss 失败不停机”。约 7148 附近“没到底不兜底”的注释/策略叙述已经过期，容易误导下一个 agent。

**建议修法：** 下一次触碰 Boss 代码时同步注释和 pure policy 测试，不要在这轮为了注释重开行为改动。

**是否阻塞单人长程：** **否**。  
**是否阻塞外发：** **否**。

### A6 — **P2** / `tools/release_gate.py:390-447` + `docs/baselines/GATE_BASELINE.json:1-48` / `GATE_BASELINE.json` 针对性手改不符合工具契约

**代码事实：** `--update-baseline` 必须带 `--reason`，并且 `main()` 明确要求**所有 STAGES 全跑**；`build_baseline()` 根据本次所有 stage observation 统一重建 baseline。当前 JSON 的 `reason` 自己写明是 “Targeted edit ... 398→399”，原因是本机完整 update run 被资源耗尽污染。

**评价：** 这次手改的两个数字从语义上很可能是对的，而且之后普通 gate 在本机已重验；但它**绕过了 baseline 的规定生成路径**，所以流程上不能叫合规更新。尤其 external-beta 依赖这份 baseline 做 strict gate，发布基线应可复现。

**建议修法：** 在资源稳定机器上运行完整 `python tools/release_gate.py --update-baseline --reason "..."`，人工审查只出现预期差异，再跑一次普通 gate 和 strict audit。以后不要直接手改 observation 数字；如果确实需要“只更新素材计数”，应先把这种 exception 做成工具显式能力和审计记录，而不是临时越过工具。

**是否阻塞单人长程：** **否**（当前本机完整普通 gate 可作为诊断前置）。  
**是否阻塞外发：** **建议视作必须清账**。

---

## 3. B — 单人长程测试就绪度

### B0 — 系统性结论

`_passenger_mode()` 当前既承担“蹭车业务规则”又承担“无人值守可靠性等级”，这是本轮最核心的架构耦合。`_hitch_liveness_supervise()` 更直接在 `src/shuabao/mediator.py:10873-10970` 以 `if not self._hitch_enabled(): return` 开头，所以**连 follow_team 都没有这套 supervisor，更不用说 normal_farm**。

最小架构改法不是把 65 处 `_passenger_mode()` 全替换，而是先拆成两个语义：

- `_passenger_mode()`：只回答“是否乘客业务”，继续控制座位、压力转移、共享道具、蹭车 L1 顺序、60s 退出等。
- `_unattended_recovery_enabled()`（名称可调整）：回答“可恢复 UI 异常是否允许重置/撤离当前局而不是停整个 runner”，至少覆盖已承诺的 `normal_farm / lobby_hitch / follow_team`。

然后把下面表里“必须移植”的恢复分支改用后者。恢复必须有预算、高层 hard cap 和 incident；**不停整机 ≠ 无限零输入**。达到高层恢复上限时优先安全结束当前局/回大厅，再开始下一轮，而不是永远 re-arm。

### B1 — 逐项分类表

| 项目 | 代码位置 | 分类 | 最小改法 | 说明 |
|---|---|---|---|---|
| 暂停恢复 5 次耗尽 | `mediator.py:7552-7580` | **单人长程必须移植** | passenger 判断换为 unattended recovery；重置预算后仍失败则记 incident / 安全退当前局 | 当前 normal_farm 直接 stop |
| 胜利页点击后不消失 | `mediator.py:14925-14945` | **单人长程必须移植** | re-arm ContinueGame + 页面重分类；总预算超限只结束本局 | passenger 已不停机 |
| ContinueGame 3 次耗尽 | `mediator.py:14943-14958` | **单人长程必须移植** | 同上 | 当前 normal_farm stop |
| 非胜利链路直接进入 ARCHIVE_PANEL | `mediator.py:14985-15005` | **单人长程必须移植** | 已有强 ARCHIVE_PANEL 证据时接管 post-game chain，而不是因“没见 Victory”杀整机 | click/分类证据仍需强约束 |
| 非胜利链路直接进入 NPC_HUB | `mediator.py:15065-15085` | **单人长程必须移植** | 强 hub 证据下恢复 post-game route；未知页不点击 | 避免动画/漏帧导致整机结束 |
| 存档面板关闭 3 次耗尽 | `mediator.py:15040-15060` | **单人长程必须移植** | re-arm close budget + bounded reobserve；高层 cap 后退当前局 | passenger 已不停机 |
| 传家宝弹窗关闭 3 次耗尽 | `mediator.py:15195-15225` | **单人长程必须移植** | 同上 | 当前 normal_farm stop |
| 未实现战后页 | `mediator.py:15295-15325` | **单人长程必须移植** | 零输入 + bounded reclassify；超高层预算后安全退当前局 | 不能把“保持运行”实现成无限等 |
| 未验证 archive 入口（两处） | `mediator.py:14878-14905, 15445-15472` | **单人长程必须移植** | 保持零输入观察/重分类；重复稳定后按已验证 route 接管，否则当前局撤离 | 当前 solo 直接 stop |
| Continue 后转场超时 | `mediator.py:15475-15495` | **单人长程必须移植** | unattended reobserve/reconcile + hard cap | 当前 passenger 无限等待也应加总预算 |
| QUIT 左上退出按钮超时 | `mediator.py:15755-15788` | **单人长程必须移植** | re-arm 低层 budget；高层 dwell cap 后重新读真实画面/回 QUIT | normal_farm 当前 stop |
| NEXT 退出确认超时 | `mediator.py:15790-15820` | **单人长程必须移植** | 同上 | 不允许盲点 |
| `_hitch_liveness_supervise` 的世界重分类/三级升级思想 | `mediator.py:10805-10970` | **单人长程必须移植（抽通用内核）** | 抽 mode-neutral supervisor；hitch 房间/搜房处理保留 delegate | 目前只 `_hitch_enabled()` |
| 战后总预算 300s / dwell cap | `mediator.py:6802-6806, 10972+` | **单人长程必须移植** | 为 normal_farm 设战后总预算；到期安全结束当前局，不杀 runner | 防止“永不 stop”变成死等 |
| 战后背包盖住页面先关背包 | `mediator.py:14755-14785` | **单人长程必须移植** | 去掉 passenger 限制，改为“已确认 post-game + bag visible”通用动作 | 09-11 已有真实遮挡事故，和乘客身份无关 |
| 面板 natural episode 上限放行/冷却重置 | `mediator.py:4115-4185` | **建议移植/统一** | 抽成面板 FSM 通用异常恢复；保持 normal_farm 自己的进度策略 | 不要复制 hitch treasure 业务选择 |
| “V 打开但无面板 = 次数不足”+物理指纹 | `mediator.py:4115-4185` 及相关 panel FSM | **建议移植** | 仅迁移“无新面板不算致命失败/不重复点击”语义；保留 solo bond/skill/treasure 顺序 | 必须用真实 panel fingerprint，不以 click success 当成功 |
| 压力转移 | passenger bootstrap 相关 | **不移植** | 无 | 蹭车业务 |
| 座位/房主/一楼规则 | lobby hitch L0 | **不移植** | 无 | 蹭车业务 |
| 蹭车误开选关页后退房/退出 | `mediator.py:14810-14835` 等 | **不移植原行为** | solo 若遇 stage 页应做自己的 stage recovery，不复制“退房/拉黑” | 业务含义不同 |
| 蹭车宝物只拿可共享道具 | `mediator.py:3606-3668` | **不移植** | 无 | solo 需要自己的卡牌策略 |
| hitch L1 `merchant→treasure→pickup→public_bag` | `mediator.py:4047-4072` | **不移植** | solo 保持 bond-first `_L1_CYCLE_ORDER` | 业务顺序不同 |
| 传家宝后“已获取装备即退 / 广场 60s 即退 / 秘境团本另等” | `mediator.py:6802+` 及 post-game branch | **需要用户定规则** | Owner 定 solo 目标：Boss 真实 Victory？装备？超时？秘境/团本？然后单独实现 | 不能复制乘客“跟房主走”的退出逻辑 |
| 单人 `auto_secret_realm` 的 NPC/确认/进入超时 | `mediator.py:15080-15300` | **需要用户定规则 + 建议恢复化** | 保留强确认门禁；定义失败时是“跳过秘境继续退出”还是“结束当前局”，不应默认停整机 | 属单人产品策略而非单纯技术异常 |
| 细体传家宝模板 | `mediator.py:6507-6544` | **已对所有模式生效** | 无需复制；需实机 | 感知层共享 |
| MAIN_LINE 顶栏否决 | `mediator.py:15505-15530` | **已对所有模式生效** | 见 A2 harden | 共享 |
| Boss 异常“末卡/跳过/不停机” | Boss handler | **已对所有模式生效** | 无需复制 | 当前符合用户规则 |
| 存档 0.35s 复核 | archive handler | **已对所有模式生效** | 无需复制 | 共享 |
| 胜利 banner / 鼠标停车 | post-game / pointer park | **已对所有模式生效** | 无需复制 | 共享 |

### B2 — **P1** / 多处 `mediator.py` / normal_farm 的“Fail-Closed”粒度过大

**失败场景：** 真实长程中出现一次动画慢、按钮没消失、暂停菜单、战后过渡漏帧或退出确认未出现，normal_farm 把“本局 UI 恢复失败”升级成“停止整个 runner”。这符合早期 fail-closed 安全原则，但和 Owner 已确认的“刷图/带队战后也不停机”的无人值守目标冲突。

**建议修法：** fail-closed 仍应保留在**动作授权**层：未知屏幕零输入；但在**生命周期**层，把“无法安全继续当前局”改成“安全撤离当前局/重分类/等待人可诊断的 BLOCKED 事件”，而不是立即杀掉所有后续局。只对真正不可恢复的环境（UIPI、窗口身份错、输入安全门、订阅拒绝、健康门禁长期失败）保留 runner-level stop。

**是否阻塞单人长程：** **是，主阻塞。**  
**是否阻塞外发：** **是**（normal_farm 是 external mode evidence 必验模式）。

---

## 4. C — `external-beta` 发布阻塞

### C0 — **P0** / `build_release.ps1:250-304` + `config/mode_evidence.json:4-9` / 外发模式证据现在会直接拒绝构建

**代码事实：** `Assert-ExternalModeEvidence` 遍历 `mode_specs.json` 中所有 `live_enabled=true && desktop_start=true` 模式，要求 `mode_evidence.json` 对应条目 `status == PASS` 且 `source_sha == 本次构建 SHA`。当前三个桌面 Live 模式均是 MISSING：

- `normal_farm`: MISSING
- `follow_team`: MISSING
- `lobby_hitch`: MISSING

**失败场景：** 即使单人长程成功，只要 follow_team 或 lobby_hitch 仍 MISSING，`external-beta` 在安装依赖/打包之前就 throw。

**建议修法：** 对 0.4 真正开放的每个模式采当前候选 SHA 的 Ground Truth bundle，并只在业务后置条件成立后更新 evidence；或者 Owner 明确缩减 0.4 外发模式，再通过 PR 修改 `mode_specs`。禁止为了过 gate 直接把 MISSING 改 PASS。

**是否阻塞单人长程：** **不阻塞测试本身**，但说明当前单人实机等级确实未完成。  
**是否阻塞外发：** **硬阻塞 P0**。

### C1 — **P0** / `src/shuabao/settings.py:117-124`, `src/shuabao/subscription_client.py:35-50`, `build_release.ps1:24-73` / 固定 HTTPS 域名未落地

**代码事实：** 两个源码默认值仍是 `https://quebec-luis-flooring-kenneth.trycloudflare.com`。云端 HTTP fetch 当前无法取得该地址；用户/本地报告为 NXDOMAIN。更关键的是订阅仓库 `ops/production-hardening-0.4-20260913` 的 `docs/G2_FIXED_HTTPS_HOSTNAME_RUNBOOK.md:1-80` 明确写：live 仍是会旋转的 Quick Tunnel，固定 hostname 需要 Owner 的 domain/Cloudflare zone/DNS/TLS，runbook 本身**没有执行切换**。

`build_release.ps1` 做对了一件事：external-beta 不会静默用源码默认，而是强制显式 `-SubscriptionBaseUrl`、absolute HTTPS、非 loopback。所以**不一定必须把生产域名硬编码进 settings.py**；真正硬要求是最终发行 manifest/构建参数绑定一个已经上线且验收过的稳定 HTTPS 地址。源码默认值随后应同步或改成明确的 dev-only 行为，避免开发/测试继续撞失效 Quick Tunnel。

**建议修法：** Owner 选固定 hostname；VPS 用现有 Named Tunnel 或 TLS reverse proxy 落地；先并行健康检查，再切 DNS；验证 `/health`、permit validate/issue、重启持久性后，客户端以显式 external URL 构建。

**是否阻塞单人长程：** **不阻塞本地离线/已授权测试**，但会阻塞真实订阅启动路径。  
**是否阻塞外发：** **硬阻塞 P0**。

### C2 — **P0** / `tools/release_gate.py:420-475`, `docs/baselines/GATE_BASELINE.json:15-33`, `build_release.ps1:369-383` / strict gate 必挂 `disconnect_modal_missing`

**代码事实：** baseline 对 `disconnect_modal_missing` 记录 `BLOCKED`，原因明确要求 `tools/net_block.py` 实机触发真实断线弹窗，禁止合成素材；external build 自动给 gate 加 `--strict-release`，strict 模式不允许 BLOCKED。

**建议修法：** 本地管理员权限触发真实断线 → 保存原始 bundle/关键帧 → 固化 fixture/ground truth → 回放与真实恢复后置条件验证 → 再正规更新 baseline。不能用合成帧或旧截图替代。

**是否阻塞单人长程：** **否**（可先测试其他链）。  
**是否阻塞外发：** **硬阻塞 P0**。

### C3 — **P0** / `build_release.ps1:115-208, 289-333` + `.github/workflows/ci.yml:95-175` / 外发签名材料尚无可验证的就绪证据

**代码事实：**

- 所有 frozen 渠道要求真实 Ed25519 manifest 私钥、key id、公钥 registry，且私钥必须在仓外。
- external-beta/release 额外要求 40 hex Authenticode thumbprint 对应的**真实证书 + 私钥**、HTTPS RFC3161 timestamp URL、真实 `signtool.exe`；主 EXE 与 OCR EXE 最终 `Get-AuthenticodeSignature` 必须 `Valid`。
- GitHub tag/frozen workflow引用 `SHUABAO_MANIFEST_SIGNING_KEY_*`、`SHUABAO_AUTHENTICODE_*`、`SHUABAO_SIGNTOOL_PATH`、`SHUABAO_SUBSCRIPTION_BASE_URL` 等 secrets。

**待核实：** GitHub connector 出于安全限制不能读取 Actions secrets，也看不到本机构建机证书存储；上一轮 09-13 审计记录的 `gh secret list` 是空。故本报告不能声称“今天仍绝对为空”，只能记**当前仓库没有可云端证明的 signing readiness；需 Owner/本地提供**。

**建议修法：**

- 如果 external-beta 走本机构建：Owner 在受控 Windows signing host 导入 Authenticode 证书私钥、manifest key/registry，跑一次完整 external 构建并验证两个 EXE 签名。
- 如果走 tag/Actions：对应 secrets 必须先配置；同时确认 Windows runner 能访问签名材料/证书（仅有 thumbprint secret 不会凭空产生证书私钥）。

**是否阻塞单人长程：** **否**。  
**是否阻塞外发：** **硬阻塞 P0，直到真实签名候选可验证**。

### C4 — **P1** / `ui-v2/index.html:4095-4140, 4290-4345` / PR #20 应在外发前合入

**代码事实：** main 仍有把启动摘要、subscription pill、modal 时间/状态等动态值拼入 `innerHTML` 的路径。PR #20 (`fix/launch-summary-escape-20260913`, head `4519970`) 已把启动摘要做 escape，并将 pill/modal 改为安全文本节点，同时增加恶意 `<img>/<svg>/event handler` payload 测试；但 PR 仍 Draft，且 merge-base 还是 `b4cf93f`，已落后当前 main。

**失败场景：** subscription/live status 或可配置字符串一旦包含 HTML，当前 dashboard DOM 可产生注入面。是否能从现有生产服务直接做到稳定 exploit 未在本轮证明，但外发 privileged QWebChannel 页面不应保留已知动态 innerHTML sink，尤其已有小范围修复可用。

**建议修法：** 基于当前 main rebase/重做 PR #20，确保三类 sink 全部关闭、现有 XSS 测试 + UI CI 通过，再 Ready/merge。不要把旧 branch 原样硬合。

**是否阻塞单人长程：** **否**。  
**是否阻塞外发：** **是，P1 安全阻塞**。

### C5 — **P1** / `shuashuabao-subscription-lab@ops/production-hardening-0.4-20260913:infra/production/*` / 服务端 hardening 代码有了，但部署/切流量证据未闭环

**代码事实：** 该分支已经比上一轮的 e2e compose 状态前进：

- `infra/production/bridge-compose.yml:1-31` 把 bridge host port 绑定到 `127.0.0.1`，挂持久 SQLite 和只读 signing key，并在 uvicorn 前跑 `production_guard`。
- `infra/production/README.md:1-90` 明确 `infra/compose/docker-compose.yml` 只是 integration/E2E fixture、不得上公网；production 路径要求 TLS reverse proxy、`/admin` 公网 404、真实凭据、持久化、permit 验收。
- README 同时明确“Do not switch production traffic ... until VPS checks ... captured”。
- `docs/G2_FIXED_HTTPS_HOSTNAME_RUNBOOK.md` 仍是 documentation only。

旧 `G2_STAGING_SOAK_NOTE` 曾记录当时 live uvicorn 为 `0.0.0.0:8010`；这是 09-05 旧证据，**不能据此断言 09-14 VPS 现在仍暴露**，当前 VPS 状态需实机/服务器侧核验。

**建议修法：** VPS 按 production compose/guard 部署到 staging/sidecar → 验 loopback-only / reverse proxy / admin deny / permit / restart persistence → 再切固定 hostname；保留 before/after 证据。

**是否阻塞单人长程：** **否**（除非测试依赖远端订阅）。  
**是否阻塞外发：** **是**。

### C6 — **P3 / 范围确认** / `shuashuabao-subscription-lab@feat/account-layer-20260913` / 账号层不是 0.4 的默认阻塞

云端确认分支仍存在，latest `cdf9603`；上一轮 release assessment 明确把账号层放到 0.5，0.4 继续现有卡密/permit 路径。本轮没有收到“0.4 external-beta 必须账号登录”的新产品决策，因此**不能把账号层 P1/P2/P3 反向升级成 0.4 发布阻塞**。

**建议：** Owner 只需确认范围：0.4 = card-key + permit；0.5 = account/lease。如果 Owner 改为“external-beta 必须账号层”，那它会立即变成新 P0 范围阻塞，需要另审，不能沿用本报告的“非阻塞”结论。

**是否阻塞单人长程：** 否。  
**是否阻塞外发：** 默认否；Owner 改 scope 时是。

### C7 — **P3** / `fix/boss-policy-fallback-layering-20260913@1b311b3` / 旧 Boss 分支不要直接合

云端 compare：该分支与 main **diverged**，merge-base 是 `b4cf93f`；main 已含 4ed44d4/63d351d 对同一片 `mediator.py` 的修改。当前 main 的 Boss 实际行为已经符合“末卡/无卡跳过/不停机”。

**建议：** 放弃/归档旧实现分支；若仍想保留 policy layering 思路，从当前 main 新分支重做，只移植纯 policy 概念和测试，不 cherry-pick/merge 旧 mediator patch。

**是否阻塞单人长程：** 否。  
**是否阻塞外发：** 否。

### C8 — **P2** / `.github/workflows/ci.yml:1-86` + Actions run #189/#190 / 当前 main 不能写成“CI 已通过”

**代码事实：** PR #21 head `6ded7ff` 的 run #189 = success；merge commit `b348da7` 的 tree id 与 PR head 相同，均为 `ec59fbce...`。但 main push run #190 = failure，主 job 在 3 秒内结束，`runner_id=0`、`steps=[]`，即测试根本没有开始。

**结论：** 这不是当前证据下的代码测试失败，但 exact main SHA 没有绿色 cloud run。交接文档“CI 通过”只能解释为“PR head 同树 CI 通过”，不能解释成“main merge SHA 的 CI 已通过”。

**建议修法：** 先查 runner/Actions 执行层原因并 rerun exact candidate；外发前要求 exact candidate SHA 绿色 CI + 本地 strict gate。

**是否阻塞单人长程：** 不阻塞短诊断；无人值守验收前建议补绿。  
**是否阻塞外发：** **是（发布治理阻塞）**。

---

## 5. D — 流程治理

### D1 — **P1** / GitHub branch metadata + repo settings + `AGENTS.md:1-120` / “只允许 PR + merge commit”当前没有硬约束

**代码/平台事实：**

- `main` 当前 GitHub branch metadata 为 `protected:false`。
- 仓库设置 `allow_merge_commit=true`，但同时 `allow_rebase_merge=true`、`allow_squash_merge=true`；因此平台并没有强制“merge commit only”。
- rulesets 读取接口对当前私有仓库返回 403（提示 plan/visibility 限制），因此本轮无法证明有其他有效 ruleset；至少 branch 自身不是 protected。
- 当前 `AGENTS.md` 的“硬规矩”覆盖 release gate、分层、fail-closed、证据纪律、工作树/构建，但**没有明确写“禁止在 main 实现/commit；必须先开 branch/worktree；只经 PR merge commit 进入 main”**。
- 4ed44d4 / 45c3520 / b66f1ce 已经真实证明：仅靠口头/交接规则不足，agent 会在本地 main 上直接 commit，事后再通过 PR #21 包装。

**失败场景：** 下一次 agent 又在 main 上实现并 commit；如果有 push 权限，可以绕过 PR；即使不直接 push，也会再次造成“先污染 main、后补流程”的不可审计状态。Squash/rebase merge 也仍可由 UI 选择。

**建议修法（优先级从高到低）：**

1. **远端硬门**：若当前 GitHub 计划允许，给 main 开 branch protection/ruleset：require PR、required status checks、禁止 force-push/delete、必要时要求 review/conversation resolved；**不要启用 linear history**（那会与 merge commit policy 冲突）。
2. 仓库设置关闭 squash merge 和 rebase merge，只留 merge commit。
3. **本地防误操作**：提交一个可跟踪的 `.githooks/pre-commit`，当前分支为 main 时拒绝 commit；`.githooks/pre-push` 拒绝直接更新 `refs/heads/main`。通过 bootstrap 设置 `core.hooksPath=.githooks`。Hook 可绕过，所以只是第二道门。
4. `AGENTS.md` 新增显式条款：任何行为修改开始前必须从最新 `origin/main` 创建 topic branch/worktree；禁止在 main 写代码/commit；发现 main 有本地未推提交即视为流程 incident，先恢复分支归属再继续。
5. CI 增加 main 历史审计（新 main tip 必须是 merge commit/满足 PR 约束）作为检测。但**没有 branch protection 时，CI 只能事后报警，不能阻止坏 push**。

**是否阻塞单人长程：** 不是运行时阻塞，但建议在下一轮实现前先把至少“禁止 local main commit”的 hook/文档补上，避免再次污染基线。  
**是否阻塞外发：** **正式外发前应完成远端治理**，至少保证发布候选的唯一主线不可被绕过。

---

## 6. 建议执行顺序

### 第一阶段：Owner 先定 3 个规则（不需要写代码）

1. **单人传家宝后的收口规则**：真实 Victory / 装备 / 超时 / 秘境·团本分别怎么结束当前局。
2. **0.4 external-beta 的模式范围**：是否同时开放 `normal_farm + lobby_hitch + follow_team`。如果 follow_team 尚未准备好，明确从 0.4 外发范围移除，而不是伪造 evidence。
3. **发布基础设施**：固定订阅 hostname；Authenticode 证书/签名 host；external 是本地签名还是 CI/tag 签名。

### 第二阶段：本地执行 agent（必须从最新 main 新 topic branch，禁止在 main 改）

1. 先做“无人值守恢复语义”最小抽取：新增 capability predicate / mode-neutral supervisor；只改通用恢复点。
2. 按 B1 表逐个把 normal_farm 的 recoverable `stop()` 改成有界恢复/当前局撤离；不搬座位、压力转移、共享宝物、hitch L1 顺序。
3. 同一分支或独立感知分支（遵循“一 commit 一层”）处理 A1：heirloom threshold 0.70 + guarded connected-component/OCR fallback；A2 用更强 stage/hub 证据处理 topbar veto。
4. 修 A3 的 treasure terminal fallback 时机；A4 先加观测/证据，不先猜原因改逻辑。
5. 为每个 normal_farm 恢复点加测试；完整 gate。baseline 不手改。

### 第三阶段：云端审查

1. 独立 review 恢复 predicate 是否误把 passenger 业务规则泛化。
2. review OCR fallback 的 action authority：必须是 plaza/post-game 强门 + ROI + 文本 + 几何，不能“识字后随便点”。
3. review PR #20 基于当前 main 的重做/更新，合并前检查所有动态 innerHTML sink。
4. 旧 Boss layering branch 归档；若要 policy layering，从新 main 重新设计。

### 第四阶段：本地 Ground Truth

1. 新候选 SHA 先做短 smoke：胜利 → Continue → 存档 → Boss → 关闭 → 广场 → 传家宝 → 退出链；专门触发至少一种可恢复异常，证明**不会杀整个 runner**。
2. smoke 通过再进入 normal_farm 多局长程；保留完整 bundle 和 postcondition，不以 click success 计 PASS。
3. 63d351d/A1/A2 涉及的传家宝字体、stage-page/topbar 场景单独留 Ground Truth。
4. 如果 external 范围含 lobby_hitch/follow_team，分别采同 SHA 真机闭环；只有业务后置条件 PASS 后才更新 `mode_evidence.json`。
5. 采真实断线弹窗素材，关闭 strict gate 的 `disconnect_modal_missing`。

### 第五阶段：VPS / 发布基础设施

1. 部署/验收 `ops/production-hardening-0.4-20260913` production topology，不使用 e2e compose 做生产入口。
2. 固定 hostname Named Tunnel/TLS sidecar 先健康检查，再人工 DNS cutover；验证 permit + restart persistence。
3. Owner 准备 signing material；本地或 CI 生成两个 EXE Authenticode `Valid` 的 external candidate。

### 第六阶段：最终 external-beta gate

必须同时满足：

- candidate SHA 的 GitHub Actions 真正执行并绿；
- 正规方式生成/确认 GATE baseline；
- `release_gate --strict-release` 全绿，0 BLOCKED；
- external modes 的 `mode_evidence` 全部 `PASS + source_sha == candidate`；
- 固定 HTTPS subscription + production permit 实测；
- PR #20/XSS 修复已合入；
- Authenticode 主 EXE + OCR EXE 均 `Valid`，manifest trust/harness 通过；
- 正式入口/冻结包 identity 与 source SHA 对齐。

满足这些后，才是 `external-beta GO`。单纯“单人长程没出大问题”只是其中一项，不足以替代其他发布硬门。

---

## 7. 最终判定

- **normal_farm 无人值守长程：NO-GO。** 主阻塞是恢复策略仍按 passenger 身份分叉；先做 mode-neutral unattended recovery，再以当前候选真实 bundle 验收。短时有人看守的诊断 smoke 可以先做，但不得把它当长程 PASS。
- **external-beta：NO-GO。** 当前至少被 external mode evidence、固定 HTTPS、strict disconnect、签名、production deployment、PR #20、exact-SHA CI 等多项独立门禁阻塞。
- **账号层：默认不阻塞 0.4。** 除非 Owner 明确改产品范围。
- **旧 Boss layering：不要直接合。** 当前 main 行为符合用户规则，旧分支应放弃或从 main 重做概念。
