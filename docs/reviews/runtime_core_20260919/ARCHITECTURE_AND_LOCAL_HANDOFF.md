# ShuaBao Runtime Core：架构实现与本地接收交接

日期：2026-09-19
状态：**OFFLINE CORE DELIVERED / LEGACY WIRING PENDING / NOT READY**
审查与接收基线：`6d55cecb50ab38675db420ccc950fd30c232ef08`
生产锚点：`b52c69e2aa1f74b59506439cceba06535bc6234c`
远端预留分支：`arch/runtime-core-handoff-20260919`

## 0. 必须先读的交付边界

本轮完成的是新的核心协议、可执行 Python 模块、独立零输入测试，以及旧代码最小接线补丁生成器。**现有 MAIN_LINE 还没有切到新仲裁器，旧代码中的 bug 也不能仅因新模块存在而算修复。**

GitHub 分支创建成功，但后续文件树写入被工具安全检查拦截。没有形成源码提交、没有推送源码、没有创建新 PR、没有合并。远端预留分支仍停在基线，**仅 fetch 该分支拿不到本交付包**。不要将一次成功创建但未被提交引用的 Git tree 当成交付。

以随包 `DELIVERY_MANIFEST.json` 的文件 hash 和 `core_foundation.patch` 为接收材料。先在独立 worktree 应用新增文件补丁，再由本地形成真正的 commit/SHA 和 Draft PR。不得把基线 SHA 填成新代码已测试的 candidate。

本轮确实执行过：新内核 78 项 unittest，全部通过；直接 unittest discovery 与独立 runner 均通过；Python 语法编译通过。报告位于交付包 `OFFLINE_VALIDATION.json` 和 `TEST_OUTPUT.txt`。报告中的 `candidate_sha=null` 是有意保留：云端没有完整 Git checkout，测试以新增源码的逐文件 hash 归因，而不是冒充某个仓库提交的全量验证。

未执行：完整仓库 release_gate、旧目标回归集、frozen replay、Windows 实机、打包与桌面同步。补丁生成器仅用合成的结构片段测试，尚未在完整生产源文件上执行生成／应用。旧基线的六个回归失败和 CI 红灯没有因此消失。

## 1. 已实现文件与职责

| 文件 | 已实现能力 |
|---|---|
| `src/shuabao/runtime_core/arbiter.py` | 显式时钟、任务注册、等待老化、到期服务优先、有限 quantum、无收益退避、相关 revision 变化后重开、超时不擅自释放、等待及 deadline-miss 诊断 |
| `src/shuabao/runtime_core/transactions.py` | 独占 lease、跨帧 postcondition、鼠标持物／遮挡收口门禁、过期进入 RECONCILE、最多一次补偿尝试、安全 release receipt |
| `src/shuabao/runtime_core/coordinator.py` | 将 grant、动作合同、事务验证与 receipt 接成同一协议；本模块不发送输入 |
| `src/shuabao/runtime_core/contracts.py` | 当前卡实例／槽位预算、基础门禁与高级顺序分离、个人／队伍归属、保守物品分流、完整目标集合的吞噬授权、资源预留 |
| `src/shuabao/runtime_core/evidence.py` | candidate／production／harness／配置／规则／资产／实际方法绑定指纹；LIVE 记录准入检查、证据文件 hash 和路径校验、已知 Runtime 重绑定检测 |
| `tools/run_runtime_core_checks.py` | 独立 unittest runner；零测试、测试数量过低或 skip 不得制造 PASS；报告明确区分 OFFLINE_UNIT 与 LIVE |
| `tools/prepare_runtime_core_integration.py` | 针对四个审查文件生成受原始 Git blob hash 保护的局部补丁；默认只检查；绝不直接修改源文件 |
| `tests/runtime_core/` | 78 项协议、故障、长序列、卡组／消费／证据与接线生成器测试 |

这些模块无 OpenCV、Qt、Windows 输入依赖，不复制截图、OCR、SendInput 或游戏决策循环。继续复用现有生产感知、执行器和领域 FSM。禁止为了方便再实现一份“云端版”识别器。

`contracts.py` 的分流是建议而非输入许可；`active_group` 是主目标选择而非完整选卡策略；`ResourceBudget` 是单资源可支付性检查而非自动推断价格的账本。装备评分所需的真实属性、英雄身份、合并配方、吞噬目标机制仍须本地补齐。现有名称词典不等于这些机制已被验证。

## 2. 不可破坏的协议

1. 一局一个 Coordinator，所有改变 UI 的任务共用；局外 L0 不得继承局内状态。新增局内字段时更新 C2 `INGAME_POLLUTION`。
2. 所有时间来自同一单调时钟；不得混用 `time.time()` 与 monotonic 秒数。Proof 的 captured_at 必须使用同一时钟域。
3. Proof.epoch 至少包括窗口身份、DPI／布局版本与相关 UI 上下文；窗口切换使旧证明失效。
4. grant 只是调度许可，不是点击许可。点击还要通过现有前台、窗口、模式、目标及语义门禁。
5. `ActionContract.authorized=True` 必须由已审查的领域授权器给出，禁止为凑接线硬编码为真。
6. 已派发动作后，只能用具名、更新帧、相关 postcondition 验证；新的普通 HUD 帧不能自动确认 pending 动作。
7. 业务提交发生在特定业务后置成立后；面板关闭、像素变化、act_click=True 不等于选卡／消费完成。
8. lease 到期保留 owner 并进入核对；不得调用 release、清空 held 或重置 deadline 来维持运行。补偿不是成功，也不能无限续期。
9. release 要有正向“鼠标已空＋遮挡已解除”证据。ABORTED_SAFE 仅证明可以安全让出 UI；受影响的卡／物品事实必须标记 UNKNOWN 并重新观测，不能当作原事务成功。
10. 若输入执行器拒绝请求，记录明确拒绝并由同一事务走安全中止；不得伪造一个成功 receipt。
11. 普通技能无收益的 revision 必须来自候选／资源可用性／构筑／规则的相关变化，不能用每 tick 的 frame_id 代替，否则会每帧重置退避。像素闪烁也不是 revision。
12. `max_wait` 是持续可执行任务取得服务尝试的工程目标，不保证游戏会给出合法卡，也不是超载下的绝对上限。所有漏期和安全阻塞都必须记录。安全阻塞不能被年龄强行绕过。
13. 高木材没有被写成 3000/1000 阈值，技能积压 8 也没有被认定为溢出。阈值校准属于后续实机数据工作。
14. 运行绑定指纹需与独立批准的 expected identity 比较；不能运行时把自己当前的指纹同时当作 expected。这些检查是可追溯性工具，不是对恶意进程的密码学证明。

## 3. 本地接收步骤：先接收，不碰原工作树

在现有仓库中只做只读检查和 fetch；已有 captures、截图、scratch、未提交改动全部保留。不得裸 stash，不得 reset --hard，不得 git clean。

创建新的 `integration/runtime-core-20260919` 分支／worktree，从基线或仍处于基线的远端预留分支开始。目标目录建议：
`G:\刷刷宝\Worktrees\runtime-core-integration-20260919`

若目录或分支已存在，不覆盖；先报告它的 HEAD、工作树状态和归属。

在新 worktree 内，对交付包进行 hash 核验，然后：

```powershell
# $Bundle 为解压后的交付包根目录；不是旧仓库目录
git apply --check "$Bundle\core_foundation.patch"
git apply "$Bundle\core_foundation.patch"

# 使用现有受控解释器；本交付没有创建新的 venv
$Python = "G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe"
& $Python tools/run_runtime_core_checks.py --report "$Bundle\local-core-checks.json"

# 默认仅核验四个旧源文件 blob，绝不修改源码
& $Python tools/prepare_runtime_core_integration.py
```

任一 source drift 或测试失败：停止接线，保留所有本地内容，回传差异。不允许修改 EXPECTED_BLOBS 来绕过校验。确认只是 CRLF 换行时，生成器已有规范化处理，不需要手工改 hash。

## 4. 本地第一批工作：P0 最小接线，不开启新调度

生成器的四文件补丁预计仅处理：

- `mediator.py`：普通丹／悬赏令／神赐丹在缺少当前实例与目标集合证明前暂时失能；无效或尺寸变化 ROI 不再作为 mutation 成功。
- `runtime_mediator.py`：inventory 委托同一 Core 方法；黑商覆写接受并传递 `allow_reroll`。
- `live_scenario_capture.py`：删除 Runtime inventory 方法重绑定。
- `choice_policy.py`：去掉 ratio=0 时放开全部高级组的旁路。

这是一道临时安全收缩，不是认定游戏永远不能吞噬，也没有自动开放新物品功能。用户开关仍是偏好，不能当作目标安全证明。

经审查生成内容后，在新 worktree 执行：

```powershell
& $Python tools/prepare_runtime_core_integration.py --write-patch "$Bundle\legacy-seams.patch"
git apply --check "$Bundle\legacy-seams.patch"
git apply "$Bundle\legacy-seams.patch"
```

必须用真正 Core、Runtime 和 `_new_live_mediator` 做参数化测试，核对实际方法绑定一致；测试黑商关键字参数；保留原有吞噬 fail-closed 测试。补充海盗真实 profile、用户显式 false、未知品质、UR 悬赏令、保护目标。不要通过更新旧 snapshot、降低阈值或修改 mock 让测试变绿。

**应用本节补丁后仍不能宣称 READY：持物状态、物品位置验证、黄金猿与银月确认链、选卡业务后置、旧循环公平性等仍需下一阶段适配。**

## 5. 本地第二批工作：唯一主循环适配器

新增一个薄适配器（建议 `src/shuabao/runtime_core_adapter.py`），由主集成 Agent 唯一负责，不修改已交付内核协议。它负责：

- 从现有感知读取 WorldSnapshot／Proof，映射机器 ID；未知保持 UNKNOWN。
- 对 G/F/V、英雄、道具、背包、拾取等生成 Demand，写清 blocked_reason 与稳定 revision。
- 主循环每 tick 先续办当前 owner，再考虑新 grant；继续复用现有 `act_*`。
- 所有释放都由同一 Coordinator 的 receipt 驱动，不允许旧 `_l1_cycle_step` 同时保留另一套输入授权。
- 在最终代替旧授权前先做 shadow 对照。shadow 必须独立于 LIVE 所有权，记录完整真实 FSM 事件和收口结果，不得把未完成的模拟 grant 永久挂住后称为算法饥饿。
- 若任务需要跨多个动作，全部子步骤保留同一 owner；每个子步骤单独验证。确认“关闭”不自动等于确认“学会技能”。
- 先接 G/F/V 和拾取；再接进化／装备；最后接物品移动和消费。未接入任务不允许与新仲裁器双重发输入。
- 新增 `_runtime_core_*` 状态只在真实新局边界初始化；同局超时不能重新 new Coordinator 清空失败账本。
- 主动开背包必须检查 Boss；Boss 出现时持物先安全补偿，再关包；无法证明安全时停止相关输入并留证。
- public bag 的 owner/asset 身份跨个人暂存格保留；移至个人格不代表获得消费权。

本地可以新增适配器、实际 postcondition、对应 integration tests 和证据文件。发现内核接口缺陷，写最小失败用例并单独回传，不要另建 scheduler/watchdog，也不要直接改内核的安全约束。

## 6. 事实、策略、产品决策

- 机器 ID `pirate.admiral_rogers` / `pirate.destruction_warship` 需由已验证名称映射；不能把任何含“海盗”的 OCR 字符串映射为同一实例。
- 当前实例的 ID 必须保持本局稳定，同一图标的多个实例不能合并去重。
- completed_goals 必须有确认事件；历史取得／吞噬词频不属于当前占槽，也不能直接变成完成事实。
- 海盗主资源优先、宝藏解锁后可插入、亡灵可在前组暂停／完成时推进；并非让测试模式放开所有卡。
- 当前没有承诺 8 张海盗就是完成，也没有把 free_slots<=4 设为固定终局。
- 消耗品默认个人包只是分流建议；即时窗口、英雄适配、神器生效位置、替换收益由真实机制补证。
- 基础经济排序与价格增长曲线暂不改。临时通用技能和 0.90 首帧直击不在本轮开放范围。

## 7. 验收顺序与证据

A. 新内核 78 项离线测试；
B. 四文件接线的真实集成测试及原有回归；
C. C2 局内／大厅隔离、完整 release_gate、frozen replay；
D. 固定本地候选 SHA 和最终配置、规则、资源、实际绑定指纹；
E. 当前候选受控 LIVE；
F. 自然整链无人工介入后，才考虑 READY。

至少覆盖：高木材+积压、无技能命中、超时关闭、F/G/V 切换、基础与高级顺序、海盗 6/8/10/12 的当前／历史区别、毁灭战舰、罗杰斯保护、悬赏令品质、普通丹保护、黄金猿解锁、银月确认、进化英雄、满栏、溢出拾取、装备适配、Boss 关包、公共资产禁止消费、替换成功、失败补偿、面板互斥、旧 candidate 拒收。

每条 LIVE 记录须有 candidate、production、harness、最终配置 hash、规则／资产 hash、绑定指纹、manifest、run.log、动作前后帧、action_id、transaction_id、具名 postcondition、失败／未知原因、人工介入标记。evidence.validate_live_record 只做准入；还要 verify_bundle_files 和人工机制复核，不能调用一个函数就给整局 PASS。

## 8. 分工与冲突控制

| 责任方 | 独占范围 |
|---|---|
| 云端架构审查 | `src/shuabao/runtime_core/`、`tests/runtime_core/`、两项新 tools 的协议与安全约束；本轮交付后不声称后台持续修改 |
| 本地主集成 Agent | 上述四个旧文件的接线、唯一适配器、C2 清单、Core/Runtime/factory 集成测试 |
| 本地机制／视觉 Agent | 只读核对素材、标签、英雄与物品机制；产出事实／候选参数，不直接修改调度入口 |
| 实机执行者 | 固定 candidate、受控采集、失败前后帧与真实后置确认；不自行扩大策略 |

先由主集成 Agent 接收提交基线，其余 Agent 再从这个本地 integration SHA 开各自 worktree。禁止多人同时修改 mediator.py、runtime_mediator.py、choice_policy.py、live_scenario_capture.py。内核修改必须单独 PR／补丁，由失败用例解释，不混入视觉参数调整。

## 9. Git 交付要求

本地必须回传：起点 SHA、最终 branch/SHA、全部修改文件、PR URL 与 base、测试命令与退出码、原有失败／新增失败、证据路径与身份 hash、是否修改 snapshots、未跟踪文件是否保留、merge 状态。

新增内核接收、L1 安全接线、Harness 一致性、适配器接管、机制补证分别做可审计提交。遵守仓库层次分离，不用一个大提交混 L0、L1、外壳与打包。

仓库原有发布门禁要求仍适用。云端 source-only PASS 不豁免完整门禁。若旧基线红灯或环境不足，先记录可复现失败；未经明确批准不得抬 baseline 或把 BLOCKED 改 PASS。

本地 push 到独立 integration 分支，创建 Draft PR，base 为审查测试分支或经重新核验的集成基线。**不开 main/生产合并，不开自动合并，不 force push，不 squash/rebase merge。**完成必要测试、证据与独立审查后，只按仓库允许的 merge commit 合并。生产锚点不得被本轮接收动作改变。
