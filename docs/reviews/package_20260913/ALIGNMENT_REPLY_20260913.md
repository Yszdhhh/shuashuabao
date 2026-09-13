# 云端审查对齐回复（2026-09-13）

对齐基准：主仓库 `main@b4cf93f6a2c716aa44f29abf1cd54caacaea09fa`，PR #20 head `9f60c97d2f472c615e6cec6c23049f9865ed89b9`，订阅仓库 `feat/account-layer-20260913@cdf960368d1b6567ca55ef7577c3805bc84bc60d`。

本文件只确认范围、分工与验收标准；不修改代码、配置或 `main`，不开 PR。

## 1. C1 路径 B：`WAIT` 达上限后 `BossLastVisibleFallback`

**同意**

接受本地复核对原 P0 的驳回，撤销“路径 B = P0 缺陷”的结论。按用户已经拍板的收口规则，连续未决后点击“当前能认出的最后一张 Boss 卡”就是目标行为；当前路径仍要求先有模板命中，不是无识别证据的盲点。

补核结果：

- `mediator.py:5839-5861`：Boss 搜索只使用两个战后列表 ROI；`_POST_GAME_BOSS_UNRESOLVED_LIMIT=3`、滚动上限 `16`。
- `mediator.py:7017-7063`：`SCROLL_DOWN/SCROLL_UP` 只有 `act_scroll()` 成功才累计滚动次数，并把 `_boss_challenge_unresolved_attempts` 清零；受约束滚动点不存在时零输入返回。
- `mediator.py:7095-7122`：只有 `WAIT` 连续达到上限后才进入 `BossLastVisibleFallback`。
- 因此我没有找到一个“在遵守规则 1 的前提下，路径 B 本身必然导致列表外点击、卡死或死循环”的具体 P0 场景。

### 1.1 `_find_last_recognized_post_game_boss()` 的真实点击边界

**同意**

本次复核没有发现当前 SHA 存在“在战后 Boss 列表 ROI 外匹配一个元素，再作为最后一张 Boss 点击”的执行路径：

- `mediator.py:6182-6215`：候选模板只来自 `assets/Images/boss/*.png` 或 `assets/Images/chuanjiaobao/*.png`，并把 `_POST_GAME_BOSS_ROIS[post_game]` 直接传给 `match_all()`。
- `matcher.py:633-739`：`match_all()` 在提供 ROI 时先裁切 `Frame`，所有模板匹配都只发生在该裁切区域，命中后再映射回原窗口坐标；灰度候选还会用原阈值做局部彩色复核。
- `mediator.py:5839-5842`：当前 ROI 分别是存档页 `(0.64, 0.24, 0.86, 0.60)`、传家宝页 `(0.30, 0.22, 0.76, 0.72)`。
- 传家宝分支在 `mediator.py:6204-6210` 解析模板序号后过滤 `1..20`；当前素材目录实际包含 `01..20` 以及异常素材 `54莫阿姆.png`，`54` 会被排除。`boss_order.py:94-116` 的 catalog 最大序号逻辑也显式排除了传家宝 `54`。

保留一个 **P3 级硬化点**：当前代码是 `no is not None and not (1 <= no <= 20)` 才拒绝，所以未来若有人往 `chuanjiaobao/` 放入“不带可解析序号”的模板，`no=None` 会被放行。当前目录里的模板都有数字前缀，因此这不是现状缺陷；如果做下面的 Boss P2 小重构，可以顺手改成传家宝候选必须满足 `no is not None and 1 <= no <= 20`。

仍存在所有模板识别都会有的“ROI 内假阳性”理论风险，但当前 helper 没有列表 ROI 外的无约束搜索，宽尺度重试也只扩大 scale、不降低 `_POST_GAME_BOSS_MATCH_THRESHOLD=0.65`；没有证据把它升级为当前缺陷。

**验收标准**：保持 `BossLastVisibleFallback` 的用户语义；测试额外断言 fallback hit 的中心始终落在对应 Boss ROI，传家宝 fallback 永不接受 `>20` 或不可解析序号的模板。

## 2. C1 路径 A：未配置目标、已到底，直接取最后已识别卡

**同意**

同意从原 P0 降为 **P2**。`boss_order.py:292-311` 的确在 `target_no is None && at_bottom && visible_cards` 时立即返回最后已识别卡，没有先复用 L+1 证明；按已拍板规则，即使先多观察几帧，最终仍允许通过路径 B 收口到最后已识别卡，所以风险主要是少了一次重新识别机会和策略语义不统一，而不是错误停机或越界点击。

**验收标准**：未配置目标时，若能证明物理末卡可立即选择；若末卡证明不足，允许先观察/取证，达到统一的未决阈值后仍按用户规则点击当前最后已识别卡；一张都认不出仍走异常重试 → skip + incident，绝不让整个运行停掉。

## 3. B2 分层：执行层把 `WAIT` 升格为业务 fallback

**同意**

同意与路径 A 合成一个小提交：把“未决计数达到阈值后选择最后已识别卡”的判断也放进纯策略输入/输出，Mediator 只负责采集、维护计数器和执行 decision；**行为不改**，仍保留 `BossLastVisibleFallback`。

同意本地倾向：这个 P2 **可以进 0.4，但不作为发布阻塞**。如果在候选 freeze 前能把改动严格限制在 `policy/boss_order.py + mediator 的薄适配 + 对应测试`，值得一起收口；如果正式候选已经冻结，则不应仅为这项 P2 重新打开大范围修改。

**分工**：主仓库执行 Agent 做一个行为保持的小提交；云端审查只做提交后复核，不直接在本轮改代码。

**验收标准**：

1. 滚动成功仍清零未决次数；
2. 未决达到 3 次且至少识别到一张卡，仍产出最后已识别卡 fallback；
3. 0 张卡仍停车、宽尺度重试、耗尽后 skip + incident；
4. 路径 A 先获得额外观察机会，但最终 fallback 语义不变；
5. Mediator 不再自行把策略 `WAIT` 改写成新的业务 action。

## 4. D1：0.4 订阅生产形态与默认凭据

**同意**

同意本地复核：`infra/compose/docker-compose.yml` 是 e2e / 集成夹具，不应直接“改几个密码”后当生产编排使用。0.4 应另建生产部署形态，不复用该文件的端口暴露和 fixture secrets。

### 4.1 0.4 实际需要的服务、`PROVIDER_MODE` 与持久化

**同意**

0.4 当前卡密激活 / entitlement validate / device activation / LIVE permit 的**最小生产服务集**建议为：

1. Caddy / Nginx：唯一公网入口，TLS 终止；
2. ShuaBao Bridge：`PROVIDER_MODE=production`；
3. Keygen CE：当前 `HttpKeygenProvider` 的主 License / Machine authority；
4. PostgreSQL：Keygen 的权威持久化；
5. Redis：Keygen 运行依赖，内部服务；
6. Bridge 自己的 SQLite：显式设置 `SUBSCRIPTION_DB_PATH` 到持久卷，保存 idempotency、subscription binding、trial/local bridge 状态。

当前 0.4 **不需要外部 Keygate 服务**：`bridge/app/main.py:47-59` 始终构造的是 `InMemoryKeygateProvider`，当前主请求路径没有依赖 compose 里的独立 Keygate 容器。

FOSSBilling + MariaDB 对“客户端激活 / 校验 / permit”不是运行时硬依赖；只有 0.4 要同时上线自动订单、支付和 webhook 驱动续期时才加入。若 0.4 继续用现有管理面人工发卡，可以先不部署 FOSSBilling/MariaDB，减少正式版服务面。

持久化边界：

- License / Machine：Keygen PostgreSQL；
- Bridge 事件、绑定、trial/idempotency：`SUBSCRIPTION_DB_PATH` 指向持久化 SQLite 文件，禁止默认 `:memory:`（`event_processor.py:17-28`）；
- signing key：预置的受保护 secret/file，不允许生产首次启动时静默生成新 key；当前 `crypto.py:15-45` 在文件不存在时会生成并写盘，生产部署应在启动前拦截这种情况；
- permit 还必须显式配置 `SHUABAO_PERMIT_SIGNING_KEY_ID` 和 `SHUABAO_APPROVED_RELEASES_JSON`，否则 `PermitIssuer` 不处于 configured 状态（`permit_issuer.py:74-117`）。

### 4.2 最小生产网络拓扑

**同意**

建议的最小形态：

```text
Internet
   |
   v
Caddy/Nginx :443
   |-- /v1/... ----------------> Bridge（loopback / 私有容器网络）
   |-- /v1/webhooks/fossbilling -> Bridge（仅部署 FOSSBilling 时开放，必须 HMAC）
   `-- /admin -----------------> PUBLIC DENY

Bridge -> Keygen（私网） -> PostgreSQL（私网）
                     `-> Redis（私网）

管理员 -> localhost / SSH tunnel / VPN -> Bridge /admin
```

- 公网只暴露 443（80 仅用于跳转/ACME 时按部署需要开放）。
- `8000/3000/5432/6379` 不直接对公网映射；若未来部署 FOSSBilling，MariaDB 同样只在内网，FOSSBilling Web 是否公网另按支付产品需求决定。
- `/admin` 在公网反向代理层直接 deny；Basic Auth 只做第二道防线。`main.py` 页面当前写着“本页只绑定 127.0.0.1”，但应用本身没有强制这一点，所以生产网络层必须把这句话变成事实。
- Keygen token、Bridge signing private key、webhook secret、管理员凭据全部从仓库外 secret store / systemd credential / Docker secret / 受保护文件注入；生产配置不允许 `${VAR:-fixture-default}`。
- 不把 e2e compose 中的 Keygen/Keygate/Postgres/MariaDB/Redis 端口映射原样带入生产。

### 4.3 哪些 `PROVIDER_MODE` 应触发生产级 fail-fast

**同意**

建议把语义分成两层：

- **正式 0.4 部署唯一允许值：`production`**。
- `real`：现有 production-like 兼容别名；只要还保留，就执行和 `production` 完全相同的强校验，并逐步弃用。
- `keygen` / `http_keygen`：代码上同样进入 `HttpKeygenProvider`，可留给 staging/诊断，但安全上应执行同样的“外部 Provider 密钥、持久化、管理员凭据显式配置”检查，不能享受 dev 默认值。
- `compose`：明确只作为 e2e fixture，**生产部署入口必须拒绝**；测试文件里可以有 fixture 值，但不能被 production deployment 引用。
- `inmemory`：开发/单测，**生产部署入口必须拒绝**。

管理员凭据本身不应该继续依赖 mode 才安全：最小改法是彻底删除 `admin/admin` fallback。生产/production-like 模式下若 `/admin` 启用但 `SUBSCRIPTION_ADMIN_USER/PASSWORD` 未显式配置，或仍是 `admin/admin`、`changeme` 等 fixture/弱默认值，应 fail-fast；更稳妥的是 admin 未显式启用时路由直接关闭。

生产级启动检查除了 admin，还应覆盖：Keygen URL/account/token、非 `:memory:` 的 `SUBSCRIPTION_DB_PATH`、预置 signing key、permit key id、approved release registry；FOSSBilling webhook 若启用则 HMAC secret 必填。这样才能避免“服务 health=green，但正式客户端拿不到 permit”的半启动状态。

**分工**：订阅仓库执行 Agent 单独做 production deployment hardening；不要改现有 e2e compose 的测试职责，新增 production 编排/启动校验。云端审查随后按部署文件 + 实际启动证据验收。

**验收标准**：

1. `PROVIDER_MODE=production` 缺任一生产 secret / persistent DB / permit registry 时启动失败；
2. `compose`、`inmemory` 被正式部署入口拒绝；
3. 公网扫描只看到反代端口，`/admin` 公网不可达；
4. 重启 Bridge/Keygen 后 license/device/binding 数据保持；
5. 生产 signing key 不由服务首次启动自动生成；
6. 真正 0.4 的 `source_sha + manifest_sha + channel + mode` 能签发 permit，未批准发行不能签发。

## 5. B1：PR #20 剩余 `innerHTML` XSS sink

**同意**

同意并入现有 PR #20，不另开 PR。对 `9f60c97` 的 `ui-v2/index.html` 全部 `innerHTML` 写入点重新扫了一遍后，**仍由 facade / 服务端字符串直接进入 HTML parser 的就是这两处，没有发现第三处同类 sink**：

1. `index.html:4304-4315`：`subscriptionPill.innerHTML` 拼入 `subscriptionPillLabel()`；该 label 可包含 `state.subscription.status / expires_at / live_status`。
2. `index.html:4319-4334`：订阅激活弹窗 `modalSheet.innerHTML` 拼入 `nowText`；激活态可包含 `expires_at / live_status`。

数据链也成立：`dashboard_facade.py:704-712` 把 `expires_at`、`live_status` 返回给前端；`dashboard_facade.py:715-729` 在部分 provider 状态下还会把 `permission.status` 原样作为状态文本。

已复核的其余 `innerHTML` 站点：章节/关卡、声望目录、Boss/传家宝静态模板目录、卡组/技能/负面宝物固定 catalog、HUD icon、静态状态 pill；这些不是 facade/服务端自由字符串。PR #20 已经对启动摘要中的搜房词和订阅字段做了 `esc()`。

另有一个**不属于本题服务端 XSS**的 P3 硬化点：自定义策略 `id` 可从 localStorage 恢复，部分 `data-id/data-del` attribute 拼接没有单独 escape；正常 UI 生成的 id 是 `custom:<timestamp>`，名称已 `esc()`，因此不建议把它混进这次 PR #20 的服务端边界修复。

**分工**：PR #20 原执行 Agent 在同一分支补这两处和对应契约测试；不开第二个 PR。

**验收标准**：

- `status/live_status/expires_at` 分别注入 `<`, `>`, 引号和事件处理器形态字符串时，pill 与 modal 只显示纯文本，不产生新 DOM 节点/attribute；
- 启动摘要现有转义测试继续通过；
- `npm test`、TypeScript check 通过；
- 不改 `src/shuabao`，因此这一项本身不触发生产代码身份基线重定。

## 6. 最终修复范围与先后顺序

**同意**

双方可以按以下三条独立小线开工，互不扩范围：

1. **PR #20 / 主仓库 UI**：补 subscription pill + modal 两个 XSS sink；P1，应在 0.4 候选 freeze 前合入。
2. **主仓库 Boss P2**：路径 A + fallback 决策下沉纯策略 + 可选传家宝 `no=None` 硬化；小提交，建议进 0.4，但不是 GO/NO-GO 阻塞。
3. **subscription-lab / 0.4 部署 P0**：独立 production topology、secret/persistence fail-fast、admin 网络隔离；这是正式对外部署前的硬阻塞。

账号 P1/P2/P3 仍留在 0.5；0.4 不增加账号层，也不增加自动更新。

## 7. 本轮是否直接云端修复

**同意**

本轮不直接修代码。虽然最后一句允许“能云端修的可以修”，但本轮 §0 的更具体约束是“只做对齐、只读、不许改代码或配置”；因此本次只提交这一个对齐文档。双方确认后，下一轮若授权执行，可以按第 6 节三条线分别施工，避免把对齐和实现混成同一个提交。
