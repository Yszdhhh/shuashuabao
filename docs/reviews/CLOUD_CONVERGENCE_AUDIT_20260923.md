# 三线交付收敛审查与架构整合契约

日期：2026-09-23。状态：**允许独立分支整理与定向验证；不允许据此发布、合并 main 或开启新调度器执行权。**

本文件完成三线基线对齐、冲突裁决、目标接口和分层施工设计。它不是完整发布验收，不覆盖本地未提交现场。代码核验来自 GitHub 固定 SHA 的文件、PR 差异、提交元数据；本轮未逐个 checkout 16 个版本跑完整门禁，未独立重做竞品反编译、图像识别和 Windows 真机测试。下文“保留/接受”均为静态处置，不等于业务 PASS。

## 1. 固定输入与 Git 拓扑

| 输入 | 精确基线 | 核验结果 |
|---|---|---|
| 架构 PR #33 | `review/current-architecture-20260923@94f502335dd3575926fc78e853f992edbb401fab` | 相对 `fix/hitch-goal-archaeology-20260920@da566dd8d2320d55df0211a4b6f43d0e671789e5` 为 16 提交、24 文件 |
| 机制与竞品 PR #32 | `docs/mechanism-convergence-20260923@14d5575fa7c2c9c1951c6c368bf175819ada68cb` | 相对 `main@7ebf4b205a1fd3acd8d9d64fd84d184db6447ebc` 为单提交、16 个 docs 文件；两份回传不是两条独立代码线 |
| 本轮整合起点 | `94f502335dd3575926fc78e853f992edbb401fab` | root tree `80af956c8c7bf897a9ccce175116dce76d22796d` |

Git compare 实际返回：`7ebf4b2 -> 94f5023` ahead 125、behind 0。因此 #33 的 16 提交不代表相对 main 的全部差异，前面还有 109 提交的基线历史。**不得把 #33 直接转投 main，宣称只合并 16 提交。**

本轮使用 `integrate/cloud-convergence-20260923`，以 #33 HEAD 为父节点导入 #32 的 16 个原始文档 blob；不移动 #32/#33/main 的 ref，不执行 merge/squash/rebase。导入是来源可追溯的内容整合，**不是声称 #32 已合并**。研究目录已有 7 个文件的 blob 与来源目录逐项一致，导入只增加 8 个研究文件；handoff 目录在目标起点不存在。

原始研究报告保留不改，不能再独立作为施工指令。实施优先级为：AGENTS 安全和 Git 规则 → 已明确的 Owner 裁定 → 当前代码及对应证据 → 本整合契约 → 原研究候选。事实证据和 Owner 偏好是两个维度；配置能说明当前行为，不能单独证明游戏机制。

### 门禁不能拼接

#33 回传是 pytest 被中止、无完整 verdict；#32 的机制回传是 600s 超时，竞品评论另报告完成一次 2/4 FAIL（Qt 用例及模板 399/401）。这是不同运行记录，不能拼成 PASS。评论把 Qt 失败归因为 flaky/无关，是作者归因，须同 SHA、同环境复现后才能采信。本轮 queried #33 combined statuses 与 PR-triggered workflow runs 均为空；这不是所有检查均通过的证据。

## 2. 必须纠偏的机制/竞品结论

| 旧报告说法 | 当前固定代码或证据 | 本轮裁决 |
|---|---|---|
| `solo_scheduler.py` 尚不存在，需新建 | #33 已有 784 行纯调度器和 461 行 shadow 适配器 | 禁止再建第二个调度器；修已有接口与证据链 |
| 点名的关键测试都不存在 | 当前树已有 Boss、devour、safety_arbitration、scheduler_and_f4、solo_core_development、near_complete 等带日期测试 | 先映射现有用例，再补真实缺口；不同文件后缀不能当作缺件 |
| 负面仅 6 张夹具，7 名/14 pattern；或 19+2 已默认禁拿 | 当前 `fixtures/treasure_negative/README.md` 记录 20 个身份；`config/choice_policy.json` 实际是 9 名、18 pattern | 两个旧结论都不能作为当前事实；夹具数量不等于默认拦截数量 |
| 扩展夹具全部默认禁拿 | 当前 policy 注记：等级优势移出、木材梭哈加入；另有诅咒之力/提高上限裁定 | 保留现有逐卡裁定；fixture README 仍有较旧叙述，不能覆盖 policy 中较新的 Owner 注记 |
| 440 杀敌预算尚未实现/应直接实现 | `_maybe_black_merchant` 已传 `_MERCHANT_REFRESH_WITH_PILL_BUDGET` 预留；shadow 模型写 350 刷新、400 丹、300 木 | 已有预算入口，仍须核准实际价格；禁止把研究 440 当生产常量，也不得把 shadow 模型价当实测价格 |
| 黑商全模式只买丹 | 当前 mediator 扫描丹、木、折扣，`rank_purchases(..., solo=...)` 分模式 | 购买丹、消耗丹、单人商品策略、蹭车商品策略四者分开 |
| 采样失败赋值 999 可直接借鉴 | 999 是数值，会被预算层当余额 | 必须用 missing/invalid，携带失败原因；未知不等于 0，也不等于足额 |
| 300s 无进展后单 ESC 安全 | 当前 runtime watchdog 明确去输入化；UNKNOWN 零输入 | 可借鉴业务进度遥测，拒绝用超时直接授权 ESC；不得新增旁路恢复器 |
| 体术已推翻为 80% 力量场域 | 同一包的收敛报告又否定该说法，缺可复核卡面证据 | 标 disputed/needs_live_check；本轮不改目录和权重 |
| 18 Boss、固定 4–5 可视槽、滚 1–4 次是通用事实 | 报告本身混有 18/21 计数及莫阿姆串项猜测 | 保留为待对账候选；不按竞品编号删除我方 Boss，不把固定滚数作为成功条件 |
| 海贼王可以直接映射海盗或赋予新优先权 | 报告自己区分海贼王/海盗；当前已有 ONEPIECE must_take 的历史配置 | 新名称映射不得自动继承特权；也不借本轮删除现有已批准 ONEPIECE 规则 |
| 技能无囤积损耗，所以应立刻删除 >=8 积压抢占 | 无过期损耗不能证明无战力兑现/调度延迟代价 | 先建立可验证等待时钟与服务定义；策略阈值留 Owner 裁定，不因研究措辞直接改优先级 |

竞品 Settings 78 项、1.6.3 九图增量、PDB 体积、竞品2版本等，本轮仅核对已提交报告及其勘误，并未重新读取本机反编译原件。因此属于“报告内纠偏/待原件复核”，不是本轮独立确认的二进制事实。保留可借鉴方向：配置语义、每房隔离、失败取证、否定证据。拒绝关闭安全软件、签名遮蔽、固定盲点、三连 ESC，以及把宣传性稳定性排名当验收。

## 3. #33 逐提交静态处置表

完整 SHA 以 PR 历史为准；下表短 SHA 唯一指向此次固定 16 提交。依据为提交元数据和累计差异、相关固定文件，不宣称对每个中间版本完成独立执行验收。

| 顺序/提交 | 改动 | 处置与依赖 |
|---|---|---|
| 1 `25284fb` | 纯 decide + boundary logger | 保留隔离方向；尚不可升格为执行调度器 |
| 2 `56d20ee` | 按窗口配对旧计划 | 部分修复；对象 identity 不是 action receipt 或事实窗口证明 |
| 3 `410e2e4` | 非法数字、同币种成本聚合 | 静态接受方向；本轮未重跑原提交测试，完整回归仍需本地 |
| 4 `2ee64fe` | confirmed ledger missing/invalid | 静态接受，不得再将未知账本填成空持有 |
| 5 `386b115` | 比较工具拒绝非零退出/计数差异 | 保留 NOT_BEHAVIOR_PROOF；pytest 数量一致仍不是行为等价 |
| 6 `9ceb40d` | 历史全量审计文档 | 保留历史基线范围；不是后续十个提交的自动验收 |
| 7 `f5a3946` | 已授权 fallback 羁绊入 pending | 避免遗漏合法持有的方向正确；仍须证明 pending 只在授权请求后建立、confirmed 只在业务确认后推进 |
| 8 `7706e44` | 主线自动任务 OFF 后完成 | 接受 click 不等于 OFF；三次尝试耗尽后仍需显式 unresolved/blocked 可观测性 |
| 9 `072ad93` | scheduler 证据边界 | 部分接受；`observed_at`/generation 尚未成为 decide 的有效性约束 |
| 10 `af6aae7` | 证据/服务 provenance | 部分接受；所有 close 都刷新服务时钟，须区分合法处理完毕与失败/遮挡关闭 |
| 11 `fc0a744` | 刷新当前帧信号 | 阻断“零扰动已证明”结论：shadow 路径主动调用 `_refresh_solo_signals`，会写 OCR 缓存/节流字段 |
| 12 `a933d9d` | 蹭车 solo/direct-end 分支 | 三种收尾结构方向正确；必须把离开旧房的确认、模式切换、计数一次性连起来验 |
| 13 `442daa0` | shell 直接结束选项 | 与 12 联合验收；持久化值、回显、后端路由须同表 |
| 14 `f353dad` | UI-23 预设/布局/接线 | 条件保留；`lastSkillsKey` 提前记成功导致失败后同值重试被吞；index.html 单列保护 |
| 15 `a979259` | identity 锚定 | 候选身份说明，不证明 dist/exe/桌面已更新 |
| 16 `94f5023` | 精确 candidate commit | 不把 candidate SHA 与包含 manifest 提交的 HEAD 不同直接判错；本地验 source/candidate/dist/exe/shortcut 身份链 |

## 4. 重点缺口及定位

### P0 约束：不要授予未知事实消费/输入权

`mediator._merchant_kill_budget_allows` 在余额 None 且单人时仍 return True，蹭车才拒绝。这是当前代码可确认的 fail-open 例外，不是本轮观察到了错误消费。建议取消该例外并保留安全重观测入口；但它涉及既有业务取舍，本轮单列 Owner-held，不静默修改。未裁定期间不得对外声称所有模式消费 fail-closed，也不得以这条旧例外放宽新调度器。

C2/C4、UNKNOWN 零输入、恢复硬截止、未确认不推进业务账本仍是先决条件。#33 新增局内时间戳、服务时钟、close 重试状态与 shadow pending；其文件清单没有修改 C2 pollution 合同。必须在真实跨局入口验证这些新状态的作用域与清理，而不是只测试手工 reset。

### P1：影子记录的四层概念仍混用

1. `_solo_shadow_tick(frame)` 在主线 tick 入口提前刷新信号，启用观察器可能改变 OCR 调用时序和节流缓存。它并非注释宣称的完全只读。要共享正常路径已形成的观察，不应为影子增加一次或提前一次识别。
2. `actual_act=str(target or '')` 只是复制计划目标，不能当实际动作。`_observe_plan` tuple 换对象只证明计划变量变化。
3. `Fact.observed_at`、page_generation、round_generation 虽被记录，但 decide 没有用它们拒绝过期、未来或跨页事实。金额缓存的可用性也不能由“当前快照取到它”证明。
4. phase_exit 清理代码在 shadow tick 内；新增调用点位于 MAIN_LINE。需要用真实 set_phase/stop/换局路径证明清理被调用，不能仅因存在分支就声明跨局配对已关闭。
5. confirmed-service 中 close 需要原因分类；打开尝试、失败隐藏、遮挡退出不能刷新“待处理机会已服务”时钟。
6. 不同家族目标默认不可比；当前同 goal/kind 的 anti-starvation 检查不足以证明 skill/treasure/bond 跨家族不会饥饿。

### P1：UI 保存确认

`ui-v2/src/main.ts::pushSkills` 先写 `lastSkillsKey`，再调用异步 `pushConfig`；后者可能因 bridge 缺失直接返回、被后端拒绝或 Promise 失败。原 key 不回滚，同配置重试会被跳过。设计必须采用 confirmed key + 独立 in-flight key，失败释放 in-flight，只有后端接受并取得匹配 revision 的快照才推进 confirmed key。不要把“发出请求”画成“已保存”。这是接线问题，不需要为修复它重做整张 index 页面。

## 5. 目标架构：一条执行链，不做第二个 Mediator

提交分层仍按 AGENTS：L0 大厅、L1 局内、恢复/战后、感知、外壳。研究中的 L0~L3 和 S1~S6 只是分析视角，不用于混层提交。

```text
既有感知路径 -> EvidenceSnapshot -> Mode/Owner 约束 -> 合法候选
             -> 现有纯 decide（shadow only）
             -> PlanObservation（旧调度仍决定）
             -> 既有输入网关的 ActionReceipt
             -> 既有业务确认器的 ConfirmedOutcome
             -> 本局 confirmed ledger / service clock
```

**本阶段不让纯 decide 调用执行器，不新增 OCR、SendInput、恢复循环、通用 watchdog、全局事件总线。** 不把 888KB 单体替换作为本轮目标；一次只抽一个可验证边界。

### 5.1 接口字段与所有权

| 概念 | 必需字段 | 唯一写入者/合法语义 |
|---|---|---|
| EvidenceSnapshot | run_id、round_generation、page_generation、frame_id、observed_at、fact.state/value/source | 既有感知适配层；缓存保留原采样时刻，不能改成快照时刻冒充新鲜 |
| Decision | decision_id、snapshot_id、候选/拒绝原因、cost currency/amount/provenance | 纯函数；不读时钟、不写账、不发输入 |
| PlanObservation | plan_id、decision_window_id、target、reason | 旧 planner 在正常计划点显式发布；不是物理动作 |
| ActionReceipt | action_id、plan_id或明确的无配对原因、request/dispatch 时刻、surface generation、网关结果 | 现有输入网关；成功发送仅为 requested/dispatched，不是业务 confirmed |
| ConfirmedOutcome | action_id、确认类型、post-frame_id、同局/同交易证明、terminal_reason | 现有 FSM/业务确认器；只有这个层可推进持有或消费结果 |

无法建立 id/窗口关联时落 `UNPAIRED`，不要用邻近时间、相似 target、对象 identity 或日志序号猜测关联。允许观测无动作，也允许恢复动作无 L1 计划，但必须如实标类型。

### 5.2 时间、事实失效与交易预算

使用同一 run 内单调时钟衡量等待/截止；墙钟只做人类日志时间。跨进程不能直接比较 monotonic 值。TTL 按信号既有采样周期和证据规定，不在这里任意新造一个全局秒数。

金额/商品报价/可点槽位：相同窗口、已知币种、非负有限数、采样有效才可授权；世代改变立即失效。刷新前要求余额覆盖“本次刷新 + 目标保留成本”；刷新后必须重新确认商品和余额/报价，不能把预算预留写成已购买。UNKNOWN_PRICE/unknown balance 都不能强行填 0 或 999。不同币种绝不相加换算。

交易执行期间保持现有 lease/pending 的排他权；低层日志不得改变其截止。超时只产生 failed/blocked outcome，并交还已有上层恢复策略；不在新抽象中藏重试或输入。

### 5.3 计划边界与跨局清理

正常 planner 的事实刷新完成后才能形成用于比较的 snapshot；shadow 只接收该不可变结果。忙碌/恢复/非 MAIN_LINE 时不创建新 L1 比较窗口。显式离开 phase、round-generation 改变、stop 都必须关闭 pending：没有对应动作就记录无动作，不带入下一局。与缓存失效/C2 清理使用同一局代际来源，不能维护互不相干的“第几局”。

对照测试必须驱动实际 Core/Runtime 主线入口：开启和关闭 shadow 时，输入网关调用序列、正常感知次数/顺序、阶段迁移一致；仅比较 pytest passed 数、推荐 target 或日志字符串均不够。

### 5.4 服务与机制状态

服务时钟按明确 outcome 更新：选卡业务确认；或在已授权面板内完成了政策允许的“本次机会处理完毕”。打开/点击请求、超时、未知页隐藏、失败关闭都不算服务。合法 give-up 是否算服务需要 policy reason 与当前家族合同，不能将所有 close 一刀切。

高级组状态 OPEN/ACTIVE/STALLED/FINISHED 可作为目标模型，但本轮不启用 >2500 木材阈值，也不废除当前 480s 实验兜底。先从 confirmed 卡账和 spend/outcome 计算状态，再单独提交策略变更。技能战力断崖 23/30/46、体术数值等未经当前帧验证的知识只能作为候选数据，不绑定执行优先级。

### 5.5 单源机制数据与 UI

不要新增与 choice_policy、catalog、lexicon 并行且互相覆盖的第四个运行时配置。先做 claim registry：每条规则记录 game_version、source_sha、asset/frame 引用、confirmed/disputed、Owner policy status、消费者路径。catalog 管身份/前置；policy 管选择偏好；lexicon 管识别别名；dashboard 只投影展示。新 catalog 真要接入，必须同一个功能闭环覆盖 loader、package manifest、policy adapter、UI DTO、合同测试，且不得在缺 catalog 时退回宽松默认。

Boss 与卡族映射分别建立 canonical id 和 aliases；竞品文件名只提供候选 alias。新模板先 staging 并有来源/版本/哈希；当前页面正向证据 + 合法槽位 + 挑战 HUD 才能证明进入成功，点击成功/面板消失/滚动过次数都不够。

## 6. Owner-held / 保护路径 / 发布链

| 项目 | 默认处理 |
|---|---|
| 单人黑商余额未知继续消费 | 建议改为 fail-closed；当前不静默改既有例外，留明确裁定及回归 |
| 新增宝物禁拿、放行、must_take、海贼王映射 | 保留当前 policy；新增一律候选，Owner 逐条批准 |
| 技能 >=8 积压抢占、480s、高级组 >2500 木阈值 | 不以研究文字直接替换，独立策略裁定与 A/B |
| `ui-v2/index.html` | 本轮仅审查风险，不修改、不回滚；隔离审批，不能混进工具修复 |
| 签名/订阅/密钥/授权数据/服务器 | 不修改；不把本轮代码整合视为发布许可 |
| runtime identity manifest | 本轮保留原文件；新增工具/docs 不代表当前 EXE 已重打包 |

没有 Owner 新裁定也可以推进非争议的事实失效、纯观察、记录完整性、UI 失败回滚和测试隔离；不要因为 held 项停掉全部整理。任何正式发版仍须完成适用的安全门禁和身份链核验。

## 7. 可执行工作包与验收合同

详细同步/Git 操作见 `docs/CURRENT_STATUS_AND_HANDOFF_20260923_CLOUD_CONVERGENCE.md`。以下为固定施工顺序，不再让每个 agent 自行创造架构。

| 包 | 主责/文件面 | 交付与拒绝条件 |
|---|---|---|
| W0 现场与资产 | 主 agent；权威 root 的 status/diff、choice_lexicon 缺失及备份 | 保存已跟踪/未跟踪/删除清单、diff、HEAD；逐项对照备份与 Git blob。不得 reset/clean/自动恢复覆盖。未完成现场不混进候选 |
| W1 L0 与恢复闭环 | 主 agent；mediator/lobby_hitch/settings；C2/C4 与 hitch 测试 | end/solo/arch 各测目标达成及预算不足；离房后置确认后才自建房；计数仅一次；host-left/UNKNOWN/失败退出无旁路输入；恢复层与 L0 分提交 |
| W2 L1 影子接线 | 主 agent；mediator/solo_shadow/solo_scheduler/runtime_mediator | 按 §5 接口只读观察，清 pending/缓存，补真实入口 on/off 对照、过期/未来/跨局事实、动作未执行、失败 close 不刷新时钟。未完成前继续 shadow only |
| W3 机制与感知 | 资料 agent 只做 registry/证据；主 agent 才改运行时消费者 | 先复用 20 身份夹具及现有 tests；逐条对账别名、Owner、价格。新 Boss 模板留 staging；不按 18/21 猜删目录，不把 440/999 写入 runtime |
| W4 UI 闭环 | UI agent；main.ts/bridge 队列/现有测试，不碰 index 保护路径 | 后端拒绝、网络失败、同值重试、连续编辑、快照回显、revision 竞争；最终 settings 与运行时目标一致。改正式入口前先读 RELEASE_HARNESS_LESSONS |
| W5 候选验证 | 主 agent + 独立 reviewer | 定向 tests -> contracts/C2/C4 -> replay/templates -> 完整 gate -> Windows 源码真机 -> 正式包身份链；每一步单独 verdict，不将前项冒充后项 |

W0 后冻结一份共同基线。运行时主 writer 唯一；UI 与资料可并行但限路径，不允许三个 agent 同写 mediator 或同一个工作区。每个功能提交带对应回归，不单独提交“先放宽门禁再补实现”。

本地 Qt 故障：保留同 SHA 的失败输出，隔离事件循环/窗口销毁/计时调度后重复执行，禁止先加 sleep 或 xfail 宣称修复。模板 399/401：对新增资产逐项核来源、hash、引用与预期数量，经审核再更新基线，不把 baseline 改大当解决。

正式包验收必须回传 source SHA、candidate SHA、UI dist hash、EXE hash、manifest hash、桌面快捷方式目标、实际 harness 路径和运行证据。Windows/UAC/真实界面未执行时明确 BLOCKED，不尝试由云端推断桌面已同步。

## 8. 本轮交付边界

三组资料内容被固定在一条独立分支，冲突裁决和跨文件接口已设计；另有独立离线 shadow 汇总工具修复与标量测试记录。本轮不修改生产 runtime、UI、catalog、签名或订阅，不执行真实输入，不改变 #32/#33/main 历史。

这不是“已替本地完成所有 runtime 重构”。本地剩余任务是按本契约实现必要接线、处理独有的未提交现场并执行 Windows/真机门禁，而不是重新研究三套互相矛盾的方案。
