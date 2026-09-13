# 设计：账号层 + 3 台设备 + 同时运行 1 台 + 云端三维分析（2026-09-13）

> 架构会话定稿。基础是用户转来的方案「在 License → Device → Permit 之上加 Account」。下面标 ✅ 的是已经对照代码核实的事实，标 ★ 的是架构会话对原方案的补充或修正。
>
> **更新（13 日 16:10）**：下文第 1 节「前提 1」已由 P0 解决。5bca48f 已推到备份分支 `backup/subscription-admin-local-5bca48f`；功能分支 `feat/account-layer-20260913`（cdf9603）已合入 origin/main 并推送。当前进度见同目录 `RELEASE_PROGRESS_ASSESSMENT_20260913.md` 第 5 节。

## 1. 现状核实

| 原方案的判断 | 核实结果 |
|---|---|
| License 已有 customer_id / customer_email / device_limit；Keygen 用 maxMachines 控制设备数 | ✅ `http_keygen_provider.py:160/207` |
| Keygen 创建设备时会处理 MACHINE_LIMIT_EXCEEDED | ✅ `http_keygen_provider.py:373` |
| 计费事件、试用创建时硬编码 `device_limit=1` | ✅ `event_processor.py:443/459`，以及各 provider 的 trial 分支 |
| SqliteEventStore 已经很胖 | ✅ 已有 7 张表（processed_events、subscription_bindings、trial_*、local_licenses、local_activations） |
| 客户端指纹 = MachineGuid →（取不到时）MAC+hostname → SHA256，`components={}` | ✅ `subscription_client.py:158/218/280-283` |
| 客户端在 LIVE 开始边界只校验一次；卡密用 DPAPI 保存 | ✅ `subscription_client.py:292-324/377` |
| Permit 字段白名单严格 | ✅ `subscription_permit.py:30` |

★ **原方案漏掉的现实前提**（都要在做账号系统之前或同时解决）：

1. **服务端代码本身没收敛**。本机实验室 `G:\刷刷宝\Worktrees\subscription-lab-642235c` 在分支 `integration/subscription-admin-local`，HEAD 是 5bca48f，**没有推送到任何远端**，还落后 `origin/main` 一个提交（cff83d0，SSBVIP 前缀）。另外 `upstreams/keygate`、`upstreams/keygen` 两个子模块有未提交的改动。
2. **本机服务是内存模式**（`PROVIDER_MODE=inmemory`），重启后数据全丢。账号系统必须建立在持久化存储上。
3. **没有稳定的 HTTPS 地址**。之前用的 trycloudflare 临时隧道已经失效。账号密码只要一出本机，就必须走 HTTPS；本机开发阶段用 loopback HTTP 可以。
4. 原方案说的客户端是 `trial-merge`，那是旧线。客户端改动要落在收敛主线（PR #19 合并后的 main）上。

## 2. 目标关系

```
Account（身份） ──1:N──> Entitlement（绑定 License，卡密只在第一次绑定时用）
License ──1:N──> Device（= Keygen Machine，付费默认上限 3，试用 1）
Account ──1:1（活跃）──> Runtime Lease（同一时刻只有 1 台设备在跑 LIVE）
Permit v1：协议不变；签发前先检查 Account + Device + Lease
```

产品规则：
- 一张卡密一旦绑定到某个账号，就**不能再被别的账号绑定**；迁移或解绑只能由管理员在后台操作，并留下审计记录。
- 限制的是「同时运行 1 台」，不是「同时登录 1 台」。其他设备可以登录、管理设备、解绑，但不能开始运行。
- 老用户不重新生成 License，也不重新计时，只要「把现有卡密绑定到账号」即可。

## 3. 服务端设计（实验室仓库 `shuashuabao-subscription-lab`）

新增独立模块，**不往 SqliteEventStore 里加东西**：`bridge/app/accounts/{account_store.py, auth_service.py, runtime_lease.py, analytics.py}`。数据库沿用同一个 SQLite 文件，schema 版本化，用迁移脚本升级。

### 3.1 表

| 表 | 关键字段 | 说明 |
|---|---|---|
| `users` | account_id, username（唯一）, password_hash（Argon2id）, status, created_at, failed_logins, locked_until, password_reset_by_admin_at | 只有用户名和密码，见第 7 节 |
| `account_entitlements` | account_id, license_id（**唯一**）, bound_at, bound_via（key / admin / migrate）, plan | 只存 license_id，**不存卡密** |
| `auth_sessions` | session_id, account_id, device_id, refresh_hash, created_at, last_used_at, revoked_at | refresh token 只存哈希，每次使用后轮换；可以按设备吊销 |
| `devices` | device_id, license_id, fingerprint_hash, hostname, first_seen, last_seen, last_release_id, unbound_at | 镜像 Keygen Machine，方便分析和展示「PC 名称 + 最后使用时间」 |
| `runtime_leases` | lease_id, account_id, license_id, device_id, release_id, mode_id, started_at, last_heartbeat_at, ended_at, end_reason, 以及计数器（games, runtime_s, boss_*、errors） | **一次运行一行**。心跳时更新计数器，不是每次心跳追加一行 |
| `usage_events` | ts, account_id, license_id, device_id, kind, detail(JSON，小体积) | 只追加、只记关键事件，见 3.4 |
| `plan_policies` | plan, device_limit, concurrent_limit | pro_monthly / pro_annual 为 3/1，trial 为 1/1；管理员可以按账号单独覆盖 |

原子性：`runtime_leases` 建一个部分唯一索引 `UNIQUE(account_id) WHERE ended_at IS NULL`。获取 lease 时用 `BEGIN IMMEDIATE`：先把 `last_heartbeat_at < now-90s` 的活跃 lease 标记为 `expired`，再插入新 lease；插入失败就返回 `ACCOUNT_IN_USE`，并附上占用设备的 hostname。

### 3.2 接口（v1，新增部分）

- `POST /v1/accounts/register`：用户名、密码，外加卡密。卡密是必填的，账号必须带着权益注册，防止批量注册空账号。
- `POST /v1/accounts/login` → 返回 access token（15 分钟）+ refresh token（30 天，轮换）。登录时自动识别当前设备：有空位就加入，满了返回 `DEVICE_LIMIT_REACHED` 和设备列表。
- `POST /v1/accounts/refresh`、`POST /v1/accounts/logout`
- `POST /v1/accounts/bind-license`：把已有卡密绑定到当前账号（老用户迁移入口）。
- `GET /v1/accounts/devices`、`POST /v1/accounts/devices/{id}/unbind`：解绑频率限制，例如 30 天内最多 3 次，超了要找管理员。这是防共享的关键参数。
- `POST /v1/runtime/lease` → lease_id，或者 `ACCOUNT_IN_USE`。
- `POST /v1/runtime/heartbeat`（30 秒一次，带计数器）→ 返回 `ok`，或 `LEASE_LOST`、`LICENSE_EXPIRED`、`REVOKED` 之一。
- `POST /v1/runtime/release`：运行正常结束时释放 lease。
- 现有的 `/v1/entitlements/validate` 和 permit 签发：带 account token 调用时，要求这个账号**持有有效 lease**才签发。旧的「只凭卡密」调用路径暂时保留，由第 6 节的发行门禁逐步淘汰。

安全要求：
- 登录、注册、绑定都按 IP 和用户名限流，连续失败会锁定。
- 管理后台不允许继续使用 admin/admin。
- 所有管理员操作（迁移、解绑、改设备上限、重置密码）都写审计记录。

### 3.3 云端分析：账号、激活码、设备三个维度（用户新增需求）

后台随时可以拉取，接口只读、需要管理员 token：
- `GET /admin/api/analytics/accounts`、`/licenses`、`/devices`：列表加聚合指标。可按时间范围、状态筛选，支持分页。
- `GET /admin/api/analytics/{accounts|licenses|devices}/{id}/timeline`：单个对象的事件时间线和运行记录。
- `GET /admin/api/export?table=runtime_leases|usage_events|devices|...&since=...`：导出 JSONL，给以后的离线分析或 BI 工具用。
- 管理页新增三个 tab：账号、激活码、设备。每行点进去就是 timeline。

每个维度的默认指标：

| 维度 | 指标 |
|---|---|
| 账号 | 绑定的激活码数、设备数 / 上限、近 7 天和 30 天的运行时长与局数、`ACCOUNT_IN_USE` 被拒次数、解绑次数、登录失败次数 |
| 激活码 | 计划类型、剩余天数、绑定的账号、设备使用率、累计运行时长、到期后仍在尝试运行的次数 |
| 设备 | hostname、首次和最近出现时间、发行版本、近 30 天运行时长与局数、Boss 收口分布（BossConfigured / LastVisibleFallback / Skipped）、错误计数 |

共享嫌疑信号（只展示，不自动处罚）：
- 近 30 天 `ACCOUNT_IN_USE` 被拒 ≥ N 次；
- 近 30 天解绑后又绑新设备 ≥ 2 次；
- 同一账号近 30 天不同 IP 段（只存 /24 前缀的哈希）过多。

隐私和数据量控制：
- 心跳只上传计数器和状态，**不传截图，不传日志正文，不传游戏角色名**；
- `usage_events` 原始记录保留 180 天，聚合数据永久保留；
- 客户端的隐私说明里写清楚上传了哪些字段。

### 3.4 `usage_events.kind` 枚举

register、login_ok、login_fail、bind_license、device_added、device_limit_rejected、device_unbound、lease_acquired、lease_rejected_in_use、lease_expired、lease_released、lease_lost、license_expired_stop、revoked_stop、admin_action。

## 4. 客户端设计（主仓库，放在 PR #19 合并之后的单独 PR）

- **看板**：新增账号区（登录 / 注册 / 绑定卡密）和设备管理（列表、解绑）。开始运行被拒时显示「账号当前正在 XXX-PC 运行」。DashboardFacade 新增 account_*、device_* 方法，属于增量改动，`BRIDGE_SCHEMA_VERSION` 升到 3，同时保持 v2 方法兼容。
- **凭据**：refresh token 用 DPAPI 保存（和现在保存卡密同一套机制）。卡密在绑定成功后**从本地删除**。
- **RunnerService**：LIVE 开始前的顺序是「获取 lease → 现有的 validate / permit」，然后启动一个心跳线程，每 30 秒一次。
- ★ **断网策略**（原方案没提）：
  - 心跳因网络失败时**不立刻停**：继续运行，连续失败超过 10 分钟（小于 permit 的 15 分钟有效期）后，在安全边界停下。安全边界指当前一局结束，或者当前处于大厅 / 房间内。
  - 服务端明确返回 LEASE_LOST、LICENSE_EXPIRED 或 REVOKED 时，也在下一个安全边界停下。
  - 停下的原因要显示在看板和日志里。
  - 这样处理，断网导致的双开窗口最多一局左右。无人值守挂机不会因为网络抖动在局中被砍掉。
- **不改设备指纹（HWID）**，也不改 Permit v1 的 schema。

## 5. 分阶段计划（每个阶段单独交付、单独验收）

| 阶段 | 仓库 | 内容 | 碰客户端吗 |
|---|---|---|---|
| P0 | 实验室仓库 | 收敛：5bca48f 合并 origin/main 并推送；子模块改动查清；确认持久化 provider 可用 | 否 |
| P1 | 实验室仓库 | 账号、认证、Entitlement 绑定、Plan Policy（3/1）、devices 镜像、usage_events、三维分析的只读 API 和管理页 tab（这一阶段先有账号、激活码、设备三个维度的静态数据和关键事件） | 否 |
| P2 | 实验室仓库 | Runtime Lease、心跳、带计数器的 runtime_leases、签发 permit 前的 lease 检查；并发抢占测试（两个线程同时 acquire 只能有一个成功）；TTL 过期接管测试 | 否 |
| P3 | 主仓库（PR #19 之后） | 看板账号区、DPAPI token、lease 与心跳、断网策略、ACCOUNT_IN_USE 提示；门禁、身份基线、lnk 都照规矩走 | 是 |
| P4 | 两边 | 新客户端发行后，停止批准旧发行版获取新 permit，旧客户端就绕不过并发限制；HWID 增强另开一轮 | 是 |

P1 和 P2 只动服务端，**和 PR #19 互不影响，可以并行**。

## 6. 老用户迁移

- 老客户端继续可用，直到 P4。
- 新客户端首次启动时，如果检测到本地还保存着卡密（DPAPI），就引导用户「创建账号并绑定这张卡」，原来的 expires_at 和已有设备保持不变。
- 卡密绑定到账号时，原样继承到期时间、已绑定设备和使用记录。
- 所有付费卡的设备上限统一是 3，由 plan_policies 决定，**和是否绑定账号无关**。已经卖出的付费卡在上线时由迁移脚本一次性把 Keygen 的 maxMachines 调到 3。试用卡保持 1。

## 7. 用户已拍板（2026-09-13）

1. **注册只要用户名和密码**。不收真实姓名，也不设备注名。
2. **忘记密码**：用户凭购买记录找管理员申诉或重置，管理员在后台重置密码并记审计。这一轮不做邮箱、手机之类的找回机制。
3. **卡密和设备的关系**：一张卡密绑定到一个账号；**一张卡密最多 3 台设备，同一时间只能 1 台运行**。卡密第一次绑定到账号时，账号**原样继承**这张卡之前的一切：到期时间、已经绑定的设备、使用记录都不变，不产生任何新东西。设备上限 3 按「每张卡密」计，所有付费卡都是 3（包括已经卖出去的卡），不存在「绑定时才升级」这一步。试用卡保持 1 台。
4. **心跳上传运行计数器**用于后台分析：同意。只传局数、时长、Boss 收口、错误数这类计数，不传截图和日志正文。
5. **断网容忍时长：10 分钟**（用户表示没概念，交给架构会话决定）。含义是：网络断开后脚本继续跑；10 分钟内网络恢复，就当什么都没发生；超过 10 分钟，把当前这一局打完再停。这个值越大，越能扛网络抖动，但别人在另一台电脑「钻空子同时跑」的窗口也越长。10 分钟短于 permit 的 15 分钟有效期，是比较稳妥的折中。
6. **解绑频率上限：30 天 3 次**（交给架构会话决定）。超过就只能找管理员。正常换电脑用不完，频繁换绑正是共享的典型信号。

关于「同时登录」：用户的原话是「只有一个能同时登录」。架构会话把它实现为「**同一时间只有 1 台能运行脚本**」，其余已授权设备可以登录，但只能查看和管理设备（比如在新电脑上解绑坏掉的旧电脑）。这样防共享的效果相同，又不会因为旧电脑没退出登录而把用户锁死。如果用户坚持要「连登录都只能 1 台」，只需把 lease 的检查点从「开始运行」前移到「登录」。
