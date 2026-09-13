# 云端执行与本地交接 — 2026-09-13

## 1. 云端已完成

### 主仓库 UI / PR #20

- `main` 保持 `b4cf93f6a2c716aa44f29abf1cd54caacaea09fa`，未直接修改。
- PR #20 `fix/launch-summary-escape-20260913@9f60c97d2f472c615e6cec6c23049f9865ed89b9` 已改为 **Draft**，防止当前两处剩余订阅 XSS sink 被误合。
- PR body 已补全剩余范围：
  1. subscription pill 的 `pill.innerHTML`；
  2. `openSubscriptionModal()` 的 `modalSheet.innerHTML` / `nowText`；
  3. 恶意载荷回归测试；
  4. `npm test` / `npm run check` / inline-script syntax gate。
- 不另开 UI PR，后续直接继续推 PR #20 head 分支。

### Boss P2 / 分层

- 已从 `main@b4cf93f6` 创建空分支：
  `fix/boss-policy-fallback-layering-20260913`
- 未修改代码。该分支专供本地做 Path A P2 + B2 分层，不与 UI PR 混合。

### 订阅 0.4 production hardening

- 生产基线不使用 `feat/account-layer-20260913`。账号系统仍归 0.5。
- 现有生产安全支线 `ops/release-lifecycle-g2-20260905@306c66a` 已经取消 admin 默认密码；
  后续 `ops/release-distribution-foundation-20260909@92ead659` 是其严格后继（ahead 7 / behind 0）。
- 已从 `92ead659` 创建：
  `ops/production-hardening-0.4-20260913`
- 当前 HEAD：`dd1f4ac5dc325cfde076726c4ca63479ddc5ee0b`
- 新增：
  - `bridge/app/production_guard.py`
  - `tests/contract/test_production_guard.py`
  - `infra/production/bridge-compose.yml`
  - `infra/production/.env.example`
  - `infra/production/nginx-shuabao-subscription.conf.example`
  - `infra/production/README.md`
  - `.github/workflows/production-hardening-ci.yml`
- 生产模式范围：`production` 为正式 0.4 模式；`real` 仅保留 legacy alias；`compose` 明确定义为 E2E fixture；`keygen/http_keygen` 只代表 provider 选择，不能自动视为生产。
- production guard 会在启动前拒绝：缺 admin 凭据、弱/fixture 默认值、缺 webhook secret、E2E Keygen account/token、缺 policy、`:memory:` 状态库、缺 signing key、缺 permit key id。
- production compose 只把 bridge 绑定 `127.0.0.1`；示例 nginx 公网拒绝 `/admin`；Keygen/Postgres/Redis 必须私网。
- 专用 GitHub Actions `Production Hardening CI` run `34749892450` 已成功：guard tests / compile / docker compose config 全通过。
- 未开 PR、未切生产流量、未部署 VPS。

## 2. 本地需要继续的工作流

### A. UI XSS（必须完成后 PR #20 才能 Ready）

在现有 `fix/launch-summary-escape-20260913` 上修改，不建新 PR：

1. 修 `ui-v2/index.html` 两个剩余动态 `innerHTML` sink：
   - `subscriptionPillLabel()` -> `pill.innerHTML`
   - `openSubscriptionModal()` 中 `nowText` -> `modalSheet.innerHTML`
2. 优先用 `textContent` / DOM node 组装；若保留 HTML 模板，所有 facade/server 动态字符串必须经过现有 `esc()`。
3. 添加恶意字符串回归，至少 `<img src=x onerror=...>`、`<svg onload=...>`、引号闭合/属性注入；证明 pill/modal 不生成可执行节点或事件属性。
4. 跑 `npm test`、`npm run check`、inline classic script syntax check。
5. commit + push 同一分支；回传 commit SHA、测试输出、PR #20 新 head 和 CI。
6. 不改 `src/shuabao`，不触发真机身份重定。

### B. Boss Path A P2 + B2 分层（建议进 0.4，但非发布阻塞）

在已建分支 `fix/boss-policy-fallback-layering-20260913` 上：

1. 用户规则保持不变：Boss 找不到目标时最终点当前能点到的最后一张已识别卡；Boss 失败不能停整个运行；一张卡都识别不到则异常重试后 skip + incident。
2. 不把 `BossLastVisibleFallback` 当 bug；本轮只做：
   - Path A 未配置目标、已到底时先增加有限重观察（P2）；
   - 把 “WAIT 累计达到上限 -> fallback click” 的策略判断移出 mediator 执行层，收回 pure policy。
3. `mediator.py` 只负责采集事实、执行 `BossOrderDecision`；不要在 `WAIT` 分支自行升格业务 action。
4. 保持滚动成功会重置 unresolved 计数；保持 16 次 scroll fuse、3 次 unresolved 收口语义或等价行为。
5. `_find_last_recognized_post_game_boss()` 仍限定 `_POST_GAME_BOSS_ROIS`；传家宝只接受 1–20。可顺手将 `parse_boss_order_number()==None` 的传家宝候选 fail-closed，但不要扩大范围。
6. 更新 policy 单测和 integration test：证明首次/有限重观察不点；达到阈值后仍按用户规则 fallback；无卡时不点并进入 anomaly retry/skip；滚动中途不会错误累计到 fallback。
7. 跑相关 pytest；若改 `src/shuabao`，必须视为新业务 SHA，后续旧 GT 不得复用。
8. commit + push 分支；不要开 PR、不要 merge，先回传云端复核。

### C. 0.4 订阅 VPS / production hardening 实机验收

基于 `shuashuabao-subscription-lab` 分支 `ops/production-hardening-0.4-20260913@dd1f4ac5`：

1. 不碰 `feat/account-layer-20260913`；账号系统不进 0.4。
2. 在本地/测试 VPS 先执行：
   - `pytest -q tests/contract/test_production_guard.py`
   - `docker compose --env-file infra/production/.env -f infra/production/bridge-compose.yml config`
3. 核对真实 VPS 当前 systemd/docker/nginx 配置和实际运行 commit，不覆盖生产；先备份 service/env/nginx/SQLite/Keygen DB。
4. 用真实 secret manager / `EnvironmentFile` 注入，不回传任何真实 secret 值；只回传变量是否配置、长度/指纹/权限等脱敏证据。
5. 目标网络：公网只 443；bridge 127.0.0.1；Keygen/Postgres/Redis 私网；公网 `/admin` 404；管理员仅 SSH tunnel/VPN/loopback。
6. 生产 bridge 必须 `PROVIDER_MODE=production`；`compose` 不得生产部署。
7. 验证 guard 缺任一关键变量/弱默认值时进程 fail-fast；正确配置时通过。
8. 验证：health、已批准 0.4 identity 获得 LIVE permit、未批准 identity 被拒、重启后 SQLite 状态保持、Keygen 状态保持、admin 错误密码拒绝、公开端不暴露 admin。
9. 若 VPS 当前仍运行 `306c66a`，不要直接覆盖；先给出从现状到 hardening 分支的最小升级/回滚步骤和 downtime 风险，再执行。
10. commit 仅用于本地发现必须修的仓库代码；VPS 配置证据写文档但不得提交 secret。最终回传部署前后 commit、服务 revision、脱敏配置检查、测试结果、是否可切流量。

## 3. 后续云端验收入口

本地三个工作流完成后，云端再统一做：

- PR #20 新 head 代码/CI 验收并决定是否 Ready；
- Boss branch diff / tests / 行为契约复核；
- subscription hardening 本地/VPS 证据验收；
- 再决定 0.4 candidate freeze、B2/B3/B4/B5 余项与最终 GT。
