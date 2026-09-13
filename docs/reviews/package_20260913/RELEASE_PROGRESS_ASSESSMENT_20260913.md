# 刷刷宝正式版（0.4）进度评估 — 2026-09-13 16:10（UTC+8）

> 架构会话自评，供外部审查复核。每一项都附了证据来源；标「未核实」的项请审查者自行验证。

## 1. 版本与分支现状

| 项 | 状态 | 证据 |
|---|---|---|
| 唯一主线 | `main` = `b4cf93f`（PR #19 的 merge commit） | `git log -1 main` |
| PR #19 合并方式 | merge commit（没有 squash / rebase），合并后的树 = PR head `79f9567` 的树（`435b266…`） | `git rev-parse b4cf93f^{tree} 79f9567^{tree}` |
| 旧 main | `7edae99` 的树与主线祖先 `9f813f8` 相同（`73ee0d5…`），是一份压缩副本；先用 `-s ours` 吸收（`87d9aca`），再合并 | 存档标签 `archive/main-7edae99-20260913` |
| PR head 上的 CI | ✅ success（run 34744566530，约 41 分钟）。标准门禁没有跑严格模式 | GitHub Actions |
| 本地发版门禁 | ✅ 4/4 PASS（pytest 2123 passed / 2 xfailed / 3 skipped，frozen_replay，scene_templates 148/148，contract 56/56） | 执行 agent 汇报 + 架构会话抽查 |
| 实机身份 | ✅ READY FOR GT（lnk → b4cf93f，Production Code Diff CLEAN） | `python tools/live_scenario_capture.py identity` |
| 在途 | PR #20：看板启动摘要转义（只改 ui-v2）；main 推送后的 CI 在跑 | PR #20 |

## 2. 这一版的功能（0.3 → 0.4）

- **新看板**：液态银主题，`DashboardFacade v2` 桥接（QWebChannel，只暴露 facade，只允许 file/qrc 协议）；蹭车 / 跟车用 360 宽的紧凑窗口，高度按内容测量；运行日志抽屉；去掉了 Esc 停止。
- **蹭车整链**：
  - 自定义多搜房词（中文）；
  - 座位规则：我方成房主、我在一楼、一楼离开，都退房并拉黑；
  - 统一的无进展监督器 `_hitch_liveness_supervise`；
  - 失败局走左上角退出；
  - 传家宝后的广场 / 秘境退出规则；
  - 宝物 V 的面板布局平票修复、三选循环修复、杀敌数门禁和有界探测。
- **战后 Boss**（`src/shuabao/policy/boss_order.py`）：
  - 按解锁序号定位，预测格位必须二次证据才能点；
  - 未解锁就点末卡；
  - 用 L+1 空格证明末卡；
  - 无滚动条列表的判定；
  - **Boss 相关失败一律不停机**：点能认出的最后一张卡，或者异常重试后跳过并记 incident。
- **CI 与测试卫生**：去掉写死本机旧工作树路径造成的「假绿」；Windows runner 上 UTF-8 解码；浅克隆时补齐基线提交。

## 3. 正式发布的阻塞项

| # | 阻塞 | 影响 | 解法 | 由谁 |
|---|---|---|---|---|
| B1 | **订阅服务没有固定的 HTTPS 地址**。之前用的 trycloudflare 临时隧道已失效；实验室默认 `PROVIDER_MODE=inmemory`（设 `SUBSCRIPTION_DB_PATH` 可以落 SQLite） | 正式版激活不了（「服务器不可到达」）。base_url 被签进发行清单，改地址就要重新打包 | VPS + Caddy，或本机 Cloudflare 命名隧道 + 自有域名 | 用户决定，执行 agent 部署 |
| B2 | **严格门禁 BLOCKED**：`frozen_replay/disconnect_modal_missing`，缺真实断线弹窗素材 | tag 构建走 `--strict-release`，会拒绝发布 | 用户用 `tools/net_block.py`（需要管理员）实机触发断线，采集素材 | 用户 |
| B3 | **签名材料**：GitHub 仓库**一个 Actions secret 都没有**（`gh secret list` 为空） | tag 触发的冻结构建会抛出「Tagged frozen builds require SHUABAO_MANIFEST_SIGNING_KEY_PEM…」 | 配置 manifest 签名密钥（Authenticode 可选），或者只在本地签名打包 | 用户 |
| B4 | **最终候选的实机验证还没做**：蹭车整链至少 3 轮、Boss 各种收口、宝物 V、公共背包、跟车、刷图 | 离线测试覆盖不到真实画面 | 用 Live 快捷方式 + trace 统计 | 用户跑，架构会话分析 |
| B5 | 已安装的正式版还是 `app-0.3-dev-17c347f` | 本机用户用的是旧版 | 解决 B1 后用 `build_release.ps1` 重新打包 | 需要用户授权 |

## 4. 还没开始的准备工作（提示词 `EXECUTOR_RELEASE_TRACK_20260913.md` 的 R1）

1. CI 提速：checkout 加 `fetch-depth: 0`；去掉和 release_gate 重复的全量 pytest，每轮约省 22 分钟。
2. 刷图 / 带队模式下战后面板还有 5 处 fail-closed 停机（mediator 约 14800、14904、14961、15107、15371 行）：改成与蹭车模式一致，加有界升级，防止无声空转。
3. 看板流畅度：主题切换单帧卡 883ms、大小窗切换单帧卡 716–750ms，页面上有 14 个 backdrop-filter。目标是最大单帧 ≤ 100ms、p95 ≤ 20ms。
4. 版本号改为 0.4，写发行说明，写发行就绪清单。

## 5. 并行线：账号系统（不进 0.4）

- 设计：`ACCOUNT_LAYER_DESIGN_20260913.md`（同目录）。关系是「账号 → 卡密 → 最多 3 台设备 → 同时只有 1 台运行（Runtime Lease）」，另有账号、激活码、设备三个维度的后台分析。
- 进度：服务端 P0 已完成（实验室仓库 `feat/account-layer-20260913` = `cdf9603`，108 passed）；P1（账号、绑定、计划策略、分析 API）在做。P2 是 lease 和心跳；P3 是客户端，放到 0.5。
- 推荐：0.4 先用现有的卡密流程；0.5 上线账号后，停止批准 0.4 获取新 permit（设计 P4）。

## 6. 风险与技术债

- `src/shuabao/mediator.py` 约 1.5 万行，是单体状态机。新策略已开始抽成纯函数（`policy/boss_order.py`），其余部分还没拆。
- CI 一轮约 41–50 分钟；私有库免费额度下 Windows runner 按 2 倍计时，今天还出现过排队 1 小时。
- 残留的工作树里有未推送的内容，请审查者判断是否需要抢救：
  - `live-harness-refresh-20260908`：未推送提交 ae52f56，另有 7 个未提交改动；
  - `subscription-lobby-pilot-20260831`：未推送提交 edccc21；
  - `live-test-boss-05ed271`：26 个未提交改动；
  - `live-g0-publicbag-v2`：2 个未提交改动；
  - `lobby-hitch-surface-test`：只有实机采集素材；
  - `night-ablation-20260907` 和 `stability-s0-20260908` 的 worktree 登记异常（指向 .git 文件）。
- 实验室仓库的子模块 `upstreams/keygen` 有一处真实改动（`scripts/entrypoint.sh`），`upstreams/keygate` 只有 CRLF 差异。
- 4 个提交标题带 UTF-8 BOM（不改写历史）。

## 7. 架构会话的结论

**代码层面**已经具备做 0.4 候选的基础：主线唯一、CI 绿、门禁绿、身份 READY、Boss 与宝物的已知 P0 都已修掉。

**发布层面还没准备好**：B1–B4 都是硬阻塞，其中 B1 和 B3 需要用户提供外部资源（服务器或域名、签名密钥）。

建议的最短路径：R1 准备工作（执行 agent）→ 用户决定 B1 / B3 → 部署订阅服务 → 采集 B2 素材 → 打包候选 → 用户做 B4 实机验证 → 打 tag 发布。
