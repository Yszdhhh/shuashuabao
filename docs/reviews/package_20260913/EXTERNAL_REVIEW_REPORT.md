# ShuaBao 外部审查报告 — 2026-09-13

审查基准：主仓库 `main@b4cf93f6a2c716aa44f29abf1cd54caacaea09fa`；订阅仓库 `feat/account-layer-20260913@cdf960368d1b6567ca55ef7577c3805bc84bc60d`。  
审查方式：本次会话通过 GitHub 远端提交图、源码、测试、Actions 元数据和审查包做只读复核；**没有在本机/Windows 实机重新执行测试**。文中“运行证据”均明确标注为仓库已有 CI/测试记录，不冒充本次独立运行。

## 1. 总体结论

`b4cf93f` 的 PR #19 合并图和合并树本身正确，主仓库可以继续作为 0.4 的代码基础；但**当前不能把它直接判为可发布候选**：Boss 末卡逻辑仍存在可绕过证据门槛的真实点击路径，订阅服务的 compose/production 路径还允许默认管理凭据。除修掉这两个 P0 外，仍需完成 B1–B4、关闭其余 P1，并用最终冻结包做一次身份绑定的真机验收后才适合发 0.4。

---

## 2. A — PR 合并与版本收敛

### A1. [P1] `main` 没有仓库级保护，“只允许 merge commit + 必须过门禁”目前主要靠人工纪律

- **位置**：GitHub `main` 分支设置；流程相关见 `.github/workflows/ci.yml`、`tools/release_gate.py`。
- **证据**：GitHub 分支 API 对 `main@b4cf93f` 返回 `protected=false`，required status checks 也没有仓库级 enforcement。
- **触发场景**：维护者直接 push、force push，或用 squash/rebase 方式把后续功能送进 `main`；现有“merge commit 才保持身份/祖先关系稳定”的约定不会被 GitHub 阻止。
- **影响**：实机身份基线、祖先判断、候选 SHA、release gate 的运维约定容易再次分叉；这是流程性 P1，不是当前 `b4cf93f` 内容损坏。
- **建议**：给 `main` 加 ruleset/branch protection：必须 PR、禁止直接 push/force push、要求关键 status checks；仓库 merge strategy 只开放 merge commit。把“身份基线更新”做成 merge 后自动生成/校验的事实，而不是靠操作者记忆。
- **验证类型**：远端设置与源码阅读；未运行。

### A2. [P2] 实机 Harness 身份检查会在浅克隆里执行 `git fetch --unshallow`，而且确实位于 Live 验收启动路径

- **位置**：`tools/live_harness_identity.py:48-72`；`live_scenario_launcher.ps1` 的 `Get-HarnessIdentity`；`tools/live_scenario_capture.py` 的 identity 路径。
- **证据**：`_ensure_commit_available()` 在目标提交缺失且仓库为 shallow 时直接 `git fetch --unshallow`，之后才尝试定深度 fetch；Live launcher 会调用 `live_scenario_capture.py identity`，而后者调用 `identity_report()`。
- **触发场景**：在 shallow checkout、离线环境、网络慢或远端历史很大的实机 Harness worktree 中点击启动前检查。
- **影响**：一个本应快速、可预测、只读的身份检查会修改 `.git` 并产生不受控网络/历史拉取，可能卡住验收，也让“检查”产生副作用。
- **建议**：把历史准备移到显式的 bootstrap/CI checkout 阶段；identity 默认不得联网。如果确需补提交，只 fetch 明确 SHA/有限深度，并把“历史不足”作为可读 BLOCKED 原因返回。
- **验证类型**：源码 + Live launcher 调用链阅读；未运行。

### A3. [P2] “收敛无损”只能对远端历史成立，对审查包列出的未推送 worktree 仍缺独立可验证证据

- **位置**：`docs/reviews/package_20260913/RELEASE_PROGRESS_ASSESSMENT_20260913.md` §6；`docs/handoff_20260912/CONVERGENCE_REPORT_20260912.md`。
- **触发场景**：残留 worktree 中确有只存在本地、后续仍需要的生产改动，而机器清理/工作树损坏后丢失。
- **影响**：GitHub 外部审查无法证明这些未推送内容“应该丢”还是“漏合”；因此不能把“全项目没有遗漏”当作已验证事实。
- **建议**：在 0.4 freeze 前只做一次资产清点：每个残留 worktree 输出 `HEAD / dirty file list / patch SHA256 / disposition(废弃、归档、后续)`；需要保留的内容推到 archive/backup 分支或保存 patch，不要求合进 `main`。
- **验证类型**：文档与远端可见历史阅读；本地 worktree 本身不可由本次外部审查验证。

### A4. 已核对正确的合并事实

以下均已用 GitHub 远端对象独立复核：

- `main` 当前确为 `b4cf93f`，是两父 merge commit，父提交为 `7edae99` 与 `79f9567`。
- `b4cf93f^{tree}` 与 PR head `79f9567^{tree}` 都是 `435b266…`，因此合并没有把旧 main 的文件树覆盖回去。
- `7edae99^{tree}` 与祖先 `9f813f8^{tree}` 都是 `73ee0d5…`；中间 `87d9aca` 的 `-s ours` 提交是零文件变更，使用依据成立。
- `archive/main-7edae99-20260913` 标签存在并指向 `7edae99`。
- `f0243f5..b4cf93f` 远端 compare 当前显示 **44 commits**，不是提示词写的 43；这是统计口径/文档差异，本身不是功能缺陷。
- PR head 的既有 CI 记录为 success；本次复核时 `b4cf93f` 的 push CI run `34746292210` 仍是 `in_progress`，不能把它写成已经成功。

---

## 3. B — 架构整合

### B1. [P1] 除已知启动摘要外，订阅状态 pill 和激活弹窗仍把后端字符串直接送入 `innerHTML`

- **位置**：`ui-v2/index.html:4290-4335`。
- **具体路径**：
  - `applySubscription(sub)` 将 `sub.status / sub.expires_at / sub.live_status` 直接放进 `state.subscription`；
  - `subscriptionPillLabel()` 返回这些字符串；
  - `subscriptionPill.innerHTML = ... ${subscriptionPillLabel()}` 未转义；
  - `openSubscriptionModal()` 把 `sub.live_status` 拼进 `nowText`，再写入 `modalSheet.innerHTML`，同样未转义。
- **触发场景**：订阅服务器、反向代理或本地测试服务返回带 HTML/event handler 的 `status` / `live_status`（例如包含可执行标签）；前端把它当 HTML 解析。
- **影响**：这是带 QWebChannel `facade` 的特权 QWebEngine 页面，XSS 不只是视觉污染，脚本可以调用页面已暴露的桥接方法。严重度 P1；如果订阅服务被攻击，影响会放大。
- **与已知项区别**：PR #20 修的是 `#selectedDeck` 启动摘要中的搜房词/订阅字段；我核了 PR #20 head，这两个 pill/modal sink **仍然存在**，所以不是重复报告已知项。
- **建议**：动态文本一律改 `textContent`；若必须模板拼接，统一 `esc()` 后再插入。至少新增 `status`、`live_status`、`expires_at` 含 `<img onerror=...>`/引号/尖括号的契约测试，断言 DOM 中只出现文本节点。
- **验证类型**：源码阅读；未在 QWebEngine 运行 payload。

### B2. [P2] Boss 规则虽已抽成纯策略，但 Mediator 仍保留能改写策略结论的业务 fallback，分层边界不完整

- **位置**：`src/shuabao/policy/boss_order.py` 与 `src/shuabao/mediator.py:7055-7145`。
- **触发场景**：纯策略返回 `WAIT`，Mediator 自己再根据 unresolved 次数改成 `BossLastVisibleFallback`。
- **影响**：策略层的安全不变量不能由策略单测完整证明；这次 C1 的 P0 正是因此产生。
- **建议**：Mediator 只采集 `at_bottom / slot evidence / visible cards / counters` 并执行 `decision`；“达到多少次以后做什么”也放进纯策略输入/输出，禁止执行层把 WAIT 升格成 click。
- **验证类型**：源码阅读；C1 有现有测试证明当前行为被编码为预期。

### B3. 已核对、未发现旁路

- `desktop_app.py` 默认进入 `WebConfigShell`；显式 native shell 仍创建同一个 `RunnerService`，启动时调用 `runner.start(...)`，没有直接 new `Mediator` 绕过 LIVE 门禁。
- `WebConfigShell` 只允许 `file/qrc` 导航/资源，并只把 `DashboardFacade` 暴露给 QWebChannel；前端 `main.ts` 的启动走 `validate_preflight → start_run`。
- `RunnerService.start()` 在 worker 前先检查 `desktop_may_start(mode_id)`、订阅 permission、单实例/Live lock；`mode_specs.json` 中桌面可启动模式与页面约定一致。
- `DashboardFacade.set_window_layout()` 对高度要求 **严格 int 且 320–1400**，宿主再按工作区高度和最小值收口；没有发现前端任意高度造成崩溃/越界的漏洞。

---

## 4. C — 业务板块

### C1. [P0] Boss “末卡必须有物理证据”仍可被两条路径绕过，能实际点错卡

- **位置 1**：`src/shuabao/policy/boss_order.py:292-304`（未配置 Boss）。
- **位置 2**：`src/shuabao/mediator.py:7085-7125`（`WAIT` unresolved fallback）。
- **测试证据**：`tests/test_boss_order_integration.py:382-414` 的 `test_boss_last_visible_fallback_when_unresolved_limit_exceeded` 明确期待 `at_bottom=False` 时第三个 tick 点击 `BossLastVisibleFallback`。

#### 路径 A：未配置目标时，到底就直接点“最后一张已识别卡”

`target_no is None && at_bottom && visible_cards` 直接取 `max(visible_cards, physical position)` 并返回 `CLICK_LAST_NOT_UNLOCKED`。这里没有像 T>L / locate failed 分支那样检查 `L+1` 物理空格，也没有确认最后一张可见但未识别的卡不存在。

- **触发场景**：列表确实到底，但最后一张真实卡模板/OCR 漏识别，倒数第二张仍被识别。
- **错误结果**：脚本把倒数第二张当“物理末卡”点击。

#### 路径 B：策略已经拒绝点击，但 Mediator 连续 WAIT 到上限后强制点击最后已识别卡

纯策略在“未证明到底 / L+1 有未识别卡 / 后续格位超视野”等情况下正确返回 `WAIT`；Mediator 却把 `_boss_challenge_unresolved_attempts` 加到上限后直接 `_find_last_recognized_post_game_boss()`，生成 `BossLastVisibleFallback` 并调用 `act_click()`。现有测试还把 `at_bottom=False`、第三 tick 点击 09 号卡写成 PASS。

- **触发场景**：目标未定位，列表还没证明到底，或真实末卡未知；连续 3 次 WAIT。
- **错误结果**：执行层绕过策略的“零输入等待”，点击最后一个**已识别**卡；这正是用户要求避免的“没有足够证据仍点击”。

#### 最小修复

1. 删除/禁止 Mediator 的 `WAIT → BossLastVisibleFallback` 升格；WAIT 达上限只能进入异常重试/skip，不能自行 click。
2. “未配置目标”的末卡选择与 T>L、locate failed 使用同一套末卡证明函数：目录上限，或 L+1 预测格位在视野内且经像素证明为空；否则 WAIT/重试/skip。
3. 改写现有测试：`at_bottom=False + unresolved limit` 必须断言 **0 click**；另加“最后真实卡存在但识别缺失”的未配置目标测试。

- **验证类型**：源码阅读 + **仓库现有集成测试反向证实错误契约**；本次未执行测试。

### C2. 宝物 V 的 MD5/物理指纹：未确认成现有 P0/P1，但有一个应补的边界测试

- **位置**：`src/shuabao/mediator.py:4070-4185`。
- `_selection_anchor(frame)` 在指纹保护之前执行；只要新三选面板被正常识别，代码会先交给面板 FSM，不会走“重复 V”保护。因此仅从静态路径看，不能断言“MD5 一定会丢新面板”。
- 但当前判断顺序是：只要 `cur_fp == unconfirmed_fp` 就直接跳过，**优先于** `has_kill_growth`；理论上“杀敌数已经增长、恰好再次出现完全相同三选画面、同时 anchor 暂时漏检”时，仍会被当作旧 mutation。
- **建议**：作为测试缺口补一个 `same fingerprint + kill growth + anchor miss` 用例，验证下一轮能重新进入选择而不是无限跳过。若实测能复现，再升为 P1；目前只列测试缺口，不把它当确定缺陷。
- **验证类型**：源码阅读；未运行。

### C3. 已核对、暂未发现新问题

- 宝物 V 在“有历史杀敌数、当前 OCR=None”时是有界跳过：5 次或 15 秒后允许一次探测，不会永久冻结；异常 episode 也有 30 秒重置窗口。
- 蹭车 L1 循环为 `merchant → treasure → pickup → public_bag`，不是终点停车；当前代码保留压力/资源循环。
- Boss 全黑/一张都认不出时的现有测试断言：先停车/异常重试，最终 0 click、不卡 ERROR、不触发 stop，并推进到关闭/下一路由；这符合“Boss 失败不停机”的方向。
- 传家宝未看到新增的每日次数上限判断；存档 8 卡策略仍是动作尝试而不是按日次数跳过。
- 蹭车模式在 `mode_specs.json` 仍显式禁止 quick join / quick match / 创房 / RoomStart fallback，和“只找房、自己不当房主”的边界一致。

---

## 5. D — 正式版进度与账号层

### D1. [P0，任何对外部署前必修] 订阅服务的 compose/production 路径允许默认管理凭据，同时 bridge 监听 `0.0.0.0:8000`

- **位置**：订阅仓库 `bridge/app/main.py:61-66`；`infra/compose/docker-compose.yml:1-31`。
- **证据**：服务端在没有环境变量时回落到固定默认管理员用户名/密码；compose 设置 `PROVIDER_MODE=compose`，把 `8000:8000` 暴露到宿主，并用 `uvicorn ... --host 0.0.0.0`，但没有要求提供管理凭据。
- **触发场景**：为解决 B1，把这套 compose 放到 VPS/公网或可被不受信任网络访问的主机，却忘记额外配置管理账号口令。
- **错误结果**：管理 API 可被默认凭据访问；现有管理面包含卡密/设备操作，并有数据库备份入口，属于直接的发行安全阻塞。
- **建议**：`production/compose/real` 启动时若未显式提供强管理凭据就 fail-fast；最好把管理面拆到 loopback/VPN/独立管理 listener，公网 bridge 不暴露 `/admin`。不要只依赖“部署的人记得改”。
- **验证类型**：订阅仓库源码 + compose 阅读；未实际启动服务。

### D2. [P1，账号层设计] Runtime Lease 的 90 秒服务端过期规则与客户端“断网继续 10 分钟”相互冲突

- **位置**：`ACCOUNT_LAYER_DESIGN_20260913.md` §3.1、§4、§7。
- **设计现状**：服务端 acquire 时会把 `last_heartbeat_at < now-90s` 的 active lease 标记过期；客户端心跳网络失败却允许旧机器继续跑 10 分钟，再等安全边界停机。
- **触发场景**：设备 A 正在跑 → 断网 91 秒 → 服务端认为 A lease 已过期 → 设备 B 成功 acquire → A 按客户端规则仍可继续约 8.5 分钟以上。
- **错误结果**：设计宣称“同一账号同时只有 1 台运行”，实际存在明显双开窗口；这不是 SQLite `BEGIN IMMEDIATE` 的原子性问题，而是**租约时效语义冲突**。
- **建议**：二选一并写成协议：
  1. 服务端 lease 占用期限至少覆盖 10 分钟 offline grace + 抖动/安全边界，期间禁止 B 抢占；或
  2. 把客户端离线继续时间缩到服务端 TTL 内，并在安全边界策略上另做短 grace。
  更清晰的方案是显式 `connected → grace → expired` 状态，只有 grace 到期才允许另一设备 acquire。
- **验证类型**：设计审查；P1/P2 账号代码尚未实现，不能做运行验证。

### D3. [P1，账号版发布边界] 只在新 account-token permit 路径检查 lease 不够；旧“卡密直签 permit”必须在 P4 同时失效

- **位置**：`ACCOUNT_LAYER_DESIGN_20260913.md` §3.2、§5；订阅仓库 `bridge/app/main.py` 当前 `/v1/entitlements/validate`。
- **触发场景**：0.5 新客户端已经受 Runtime Lease 限制，但旧 0.4 客户端仍能只凭卡密请求新 permit。
- **错误结果**：共享者可用旧客户端绕过“同一时刻 1 台运行”，因此 lease 不是安全边界。
- **建议**：把 P4 变成账号版的发布硬门禁：服务端按发行身份/source/channel 拒绝旧发行获取新 permit，或对所有 permit 签发统一要求可验证 lease；在正式启用账号限制前做“旧客户端请求 permit 必拒”的端到端验收。
- **验证类型**：设计 + 当前服务端源码阅读；未运行。

### D4. [P2] `feat/account-layer-20260913@cdf9603` 目前只是账号层 P0 前置，不能用“108 passed”替代账号层原子性验收

- **位置**：订阅仓库 `cdf9603` 与其基线的 commit/file diff；`ACCOUNT_LAYER_DESIGN_20260913.md` §5。
- **事实**：当前分支主要是 permit 签发身份/发布绑定收口及测试；尚没有设计里的 `users / account_entitlements / auth_sessions / runtime_leases / usage_events / plan_policies` 实现。
- **影响**：`BEGIN IMMEDIATE + partial unique index`、并发 acquire、TTL takeover、token rotation、解绑限频都还只是设计；不能把分支的 108 tests 当作这些能力已经通过。
- **建议**：P1/P2 分阶段验收，至少必须有：两个并发连接同时 acquire 仅一方成功、进程崩溃/重启后 lease 仍正确、TTL/grace 交接、旧 permit 路径拒绝、refresh token 单次轮换、解绑频率的并发测试。
- **验证类型**：远端 diff + 设计阅读；订阅仓库该分支没有 Actions run，本次未执行其本地测试。

### D5. [P2] 0.4 已有版本化安装和本地回滚，但**没有自动更新器**；进度评估应明确这是非目标/产品缺口

- **位置**：`src/shuabao/versioned_install.py:1-4`（模块明确写 `No ... updater`）；`RELEASE_PROGRESS_ASSESSMENT_20260913.md`。
- **触发场景**：把 0.4 对外描述为“可自动升级”，或发布后需要远程推送 0.4.1。
- **影响**：当前能力是版本化 `app-*`、atomic `current.json`、稳定 launcher 和本地 rollback，不是在线更新。
- **建议**：0.4 如果接受“手动下载安装/重新运行发布脚本”，自动更新**不必成为硬阻塞**，但必须在 release checklist/说明里明确不支持；若产品承诺自动更新，则另开独立 release track，不能把 versioned installer 当 updater。
- **验证类型**：源码阅读；未运行安装/回滚。

### D6. [P2，0.5 前] 账号分析的隐私边界有方向，但缺可验收的数据生命周期/删除规则

- **位置**：`ACCOUNT_LAYER_DESIGN_20260913.md` §3.3–3.4。
- **现状**：设计已限制“不传截图、不传日志正文、不传游戏角色名”，IP 只保存 `/24` 前缀哈希，`usage_events` 180 天、聚合永久保存，这是合理起点。
- **缺口**：尚未看到用户侧隐私说明文本、账号删除/管理员删除后的清理规则、导出权限审计、永久聚合是否可回溯到账号的去标识标准。
- **建议**：0.5 前补一页数据清单和 retention/deletion matrix，并用服务端测试证明 180 天清理任务和 admin export 鉴权；不阻塞 0.4，因为账号系统明确不进 0.4。
- **验证类型**：设计审查。

### D7. 对 B1–B5 的复核

- **B1 固定 HTTPS 服务**：准确，仍是 0.4 硬阻塞；同时必须先修 D1，不能为了“有固定地址”把默认管理凭据直接暴露公网。
- **B2 严格门禁的断线素材**：按任务要求视为已知项，不重复报。
- **B3 Actions secrets/签名材料**：按任务要求视为已知项，不重复报。
- **B4 最终候选实机验证**：准确，而且在 C1 修复之后必须重跑，旧 READY/GT 不能替代新 SHA。
- **B5 本机仍装 0.3**：准确，但属于部署状态；0.4 候选冻结并通过 harness 后再 promote 新 `app-*` 即可。
- **安装/回滚**：版本化 installer 已存在，未发现还停留在历史“直接 MIR 覆盖桌面 EXE”的架构缺口。
- **OCR 分发**：现有 release 设计/构建链把 OCR sidecar/模型当冻结包组成部分并由 manifest/harness 约束；本次没有发现新的独立阻塞，但仍应在最终包上做 OCR worker 启动自检。

---

## 6. 测试缺口清单

1. **Boss P0 必补**：
   - `at_bottom=False + unresolved == limit` 必须 0 click；
   - `target=None + at_bottom=True + 最后一张真实卡未识别` 必须 0 click/继续取证；
   - L+1 有物理卡但模板/OCR 不命中时不得点 L；
   - 两种页面（存档/传家宝）都跑相同安全断言。
2. **Boss 测试卫生**：减少把 `_post_game_boss_list_at_bottom`、finder 直接 patch 成最终结论的测试；至少保留一组从真实 fixture → card detection → at_bottom/slot proof → decision → click recorder 的整链离线测试。
3. **订阅 DOM 安全**：除 launch summary 外，给 `subscriptionPill`、subscription modal 注入恶意 `status/live_status/expires_at`，断言无节点/事件注入。
4. **宝物 V**：`same fingerprint + kill growth + anchor temporarily missing`；以及 OCR=None 连续 4 次不点、第 5 次只允许一次探测、探测后预算重置。
5. **账号 Lease**：两连接并发 acquire、进程重启、90s/未来 grace 语义、server clock skew、release/acquire race、同账号不同 license 的策略必须写清并测试。
6. **旧客户端绕过**：账号版上线前必须保留一个真实 0.4 请求格式，证明 P4 后拿不到 permit。
7. **管理面部署安全**：production/compose 缺 admin secret 必须启动失败；公网 listener 上 `/admin` 的暴露策略需要集成测试/部署检查。

---

## 7. 已核对、没发现问题的部分

- PR #19 merge tree、`-s ours` 前提、archive tag 都成立；没有发现远端合并把 PR head 内容覆盖掉。
- desktop web shell / native shell 最终都通过 `RunnerService`，没有发现直接绕过唯一 LIVE 入口的桌面旁路。
- `mode_specs.json` 的 desktop start gate 与 RunnerService 后端校验同时存在；UI 不是最终授权源。
- `set_window_layout` 高度类型/范围校验完整。
- 宝物 V 的 OCR=None 跳过是有界的，不是永久禁用；passenger V episode 也会按窗口重置。
- Boss “一张都认不出”的异常路径有 0 click + skip/continue 测试，方向正确；问题集中在“还能认出一张时过早把它当末卡”。
- 现有 permit v1 对 source SHA / manifest SHA / release channel / mode / TTL / Ed25519 的绑定设计没有要求为账号层改 schema；**协议本身可以保留 v1**，问题只在签发前的 lease gate 与旧路径淘汰。
- 版本化安装、atomic current pointer、launcher、本地 rollback 已有实现；自动更新是另一个能力，不应混为一谈。

---

## 8. 建议的最短发布路径与验收标准

### Step 1 — 先修两个 P0，再谈候选冻结

1. **Boss P0**：去掉 `WAIT → visible fallback click`，未配置目标也统一做末卡物理证明。
   - 验收：上述 Boss 新测试全绿；现有 Boss 测试不得再期待 `at_bottom=False` 时点击。
2. **订阅管理 P0**：production/compose 缺管理凭据 fail-fast，管理 API 不直接暴露公网。
   - 验收：缺凭据启动失败；正确 secret 启动成功；外部 bridge 访问策略与部署文档一致。

### Step 2 — 收 P1，形成新的唯一候选 SHA

- 修订阅 pill/modal XSS。
- 给 `main` 加 ruleset/branch protection（不改历史）。
- 账号层不进 0.4；D2/D3 是 0.5 设计门禁，不拖住 0.4。
- 验收：新 SHA 上主仓库 CI 全绿；release gate 非 strict 部分全绿；GitHub merge strategy/required checks 可从仓库设置复核。

### Step 3 — 完成现有 B1/B2/B3 的发行基础设施

- B1：固定 HTTPS + 持久化 provider；同时满足 D1。
- B2：补真实断线素材，让 strict release gate 绿。
- B3：配置真实 manifest signing（以及实际采用的 Authenticode 路径）。
- 验收：`build_release.ps1` 在目标 release channel 不使用 `-SkipGate/-AllowDirty` 成功生成冻结包；manifest/identity/harness 全部通过。

### Step 4 — 冻结候选包，做“包身份”而不是“源码工作树”验收

- 构建新的 `app-0.4-<channel>-<sha12>`，不要继续用旧 0.3 安装。
- 验收：launcher → `current.json` → 0.4 包；EXE hash、manifest canonical SHA、source SHA、channel、OCR worker/model 都通过 release harness；rollback 能切回 previous 而不重建。

### Step 5 — 最终 B4 真机 Ground Truth

至少覆盖：

- 蹭车自然整链 ≥3 轮；房主/一楼/一楼离开三种退出拉黑规则；压力按钮可见/不可见两种。
- Boss：T≤L、T>L、未配置、目标定位失败、L+1 有未识别卡、全黑异常、存档/传家宝关闭后继续下一局。
- 宝物 V：正常三选、OCR=None 有界探测、相同/变化指纹。
- 跟车、正常刷图、公共背包。

**验收标准**：只认真实业务 postcondition；click success、frame change、bookmark、离线 replay 均不能替代 GT PASS。任何 `src/shuabao` 修复都产生新 SHA，旧 GT 不继承。

### Step 6 — 发 0.4

- 版本号/发行说明/隐私说明（仅覆盖 0.4 实际上传内容）与最终包一致。
- 明确写“0.4 暂无自动更新；采用版本化安装 + 本地 rollback”。
- tag 只指向已经通过 Step 3–5 的唯一候选 SHA；发布后再开始 0.5 账号 P1/P2/P3，不把未完成账号层混入 0.4。

---

## 9. 账号层后续（0.5）的最低验收线

“0.4 不等账号系统”是合理的：当前 `cdf9603` 还只是前置收口，把 P1/P2/P3 塞进 0.4 只会扩大风险面。0.5 真正启用账号限制之前，至少必须同时满足：

- SQLite acquire 原子性在真实并发连接下只有一个成功；
- offline grace 与 server TTL 统一，不出现未声明的双开窗口；
- permit 签发统一受 lease 约束，旧 0.4 请求在 P4 后确实拿不到新 permit；
- 老卡迁移幂等、可回滚，原 expires/device/history 不被重置；
- refresh token 只存哈希并轮换；解绑限频并发安全；
- usage/analytics 的字段、180 天保留、永久聚合、删除/导出/审计规则落到代码与用户说明，而不只停留在设计文档。

**最终判定：当前 `b4cf93f` = 可继续修成 0.4 候选的正确主线基座，但不是可直接发布的 0.4 候选；修复 C1/D1 后再重定候选 SHA并重跑门禁与 GT。**
