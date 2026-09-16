# 云端审计提示词（2026-09-14）

> 由本地架构/收敛会话编写。把分隔线以下全部内容粘贴给云端审计 agent。

---

你是刷刷宝项目的外部审计员。仓库 `github.com/Yszdhhh/shuashuabao`，**唯一主线 `main` = `b348da7`**（只允许 PR + merge commit）。这次审计的目的是回答两个问题：

1. **能不能回到单人（`mode_id=normal_farm`）长程测试？**
2. **长程测试没有大问题的话，能不能打外发正式版（`external-beta`）？**

只读审计：不要改代码、不要开 PR、不要合并。报告写到新分支 `review/audit-20260914`（从 main 拉），文件 `docs/reviews/CLOUD_AUDIT_20260914.md`，只提交这一个文档。

## 1. 先读这些（按顺序）

1. `docs/handoff_20260914/ARCHITECTURE_STATUS_20260914.md`：运行主链路、各环节验证等级、并行线、发布阻塞。
2. `docs/handoff_20260914/LOCAL_AUDIT_20260914.md`：本轮本地审计和传家宝 P0 的根因。
3. `docs/handoff_20260914/HITCH_AUDIT_HANDOFF_20260914.md`：执行 agent 对 b66f1ce 的交接说明（其中"传家宝过渡块已修好"的结论被本地审计推翻，请独立核实）。
4. 上一轮云端审计：分支 `review/package-20260913`（`c1b9991`）下 `docs/reviews/package_20260913/` 里的 `EXTERNAL_REVIEW_REPORT.md`、`RELEASE_PROGRESS_ASSESSMENT_20260913.md`、`CLOUD_EXECUTION_AND_LOCAL_HANDOFF_20260913.md`。
5. `AGENTS.md` 和 `docs/agent_shared_logs/RELEASE_HARNESS_LESSONS.md`（发布硬规则）。

## 2. 上一轮云端审计（基线 `main@b4cf93f`）之后改了什么

范围 `b4cf93f..b348da7`，17 个文件，+679/−206：

| 提交 | 改动 | 修掉的旧问题 |
|---|---|---|
| 4ed44d4 | 宝物 V：去掉杀敌余额门槛，异常重试 30s→8s，V 前后用面板指纹判断是不是新面板；存档 8 卡复核固定 0.35s；Boss 网格"上一行满 + 下一格空"的末行证据；传家宝链路条件放宽 | 蹭车整局 V 被杀敌余额卡死；存档 8 卡太慢；Boss 在列表中间误判到底 |
| b66f1ce | 宝物刷新预算用完后兜底选非负面卡（OCR 读不出名字就点第 1 张）；存档关闭过渡帧保护 | 实机：刷新次数不足的面板被 hide→重开 循环 |
| **63d351d** | **传家宝入口加细体标签模板 `assets/Images/chuanjiabao_thin.png`；顶栏模式标签（存档/团本）否决两处"选关页"退出；b66f1ce 的过渡块挪到"战后先关背包"之后** | **实机 P0：广场 NPC 标签鼠标悬停时是粗体、否则是细体，旧模板只认粗体 → 第二局传家宝没点（09-13 那一轮也漏过）；广场被误判成选关页 → 传家宝后的 60s 规则第 14 秒就被截断** |
| 34c103f / 45c3520 | Live 身份基线 | — |
| 6ded7ff | 审计/架构文档；`GATE_BASELINE.json` 素材数 398→399（针对性手改） | — |

更早（已在上一轮审计范围内，这里只列出来对照）：09-12 通用无输入监督 `_hitch_liveness_supervise`、胜利横幅/鼠标停车、宝物布局平票；09-13 Boss 顺序定位 `policy/boss_order.py`、Boss 失败不停机、看板蹭车设置。

**当前验证状态**：
- CI 通过。
- 本机完整 `release_gate`：PASS 4/4（pytest 2137 通过、0 失败；frozen_replay 中 `disconnect_modal_missing` 仍是已登记的 BLOCKED）。
- 正式版 `app-0.3-dev-b348da79d85c` 已本地安装（dev 渠道，已签名）。
- 63d351d 只有**离线真实帧**证据（夹具 `tests/fixtures/hitch_postgame_20260914/`），还没有实机回归。

## 3. 审计维度

### A. 本轮改动的正确性（`b4cf93f..b348da7`）
每条结论都要给出 `文件:行号`、具体会失败的场景和修法。重点看：
1. 传家宝入口 `_find_post_game_hub_entry`（mediator.py 约 6510）：只靠模板匹配（灰度归一化互相关）。换字体、换分辨率、客户端更新后会不会又失效？项目里的 OCR（`vision/ocr_shadow`）只做"给框识字"，不做检测——请评估一个兜底方案：广场顶栏已确认是"存档"，但两张模板都没命中时，在标签 ROI 里按白字连通域切出词框 → 逐框 OCR 找"传家宝"→ 点标签下方。另外看阈值：粗体模板在"存档挑战"上能打到 0.573，和 0.58 的阈值只差一点，是否应把传家宝入口阈值提到 0.70（真实命中都 ≥ 0.83）。
2. 顶栏否决（约 14790 行和 15515 行）：有没有"顶栏识别到存档，但确实应该退出"的场景（例如秘境 / 团本 / 广场上确实误开了选关页）？
3. b66f1ce 宝物兜底（约 3635 行）：OCR 读不出名字、又没检测到刷新钮时，**第一次打开就盲点第 1 格**，这样是否可以接受？
4. 4ed44d4 去掉杀敌余额门槛以后，频繁开 V 会不会反复触发"宝物选择次数不足"，进而把聊天条打开（实机里聊天条在第二局几乎常开）？
5. 4ed44d4 Boss WAIT 到上限后，是否实际仍走 `_handle_boss_anomaly_retry_or_skip` 点可见末卡（约 7148 行注释说的是"没到底不兜底"，与实际行为不一致）？是否符合用户规则："找不到目标就点能点到的最后一张卡；一张都认不出就跳过；任何 Boss 失败都不停机"。
6. `GATE_BASELINE.json` 的针对性手改是否合规（对比 `tools/release_gate.py` 的 `build_baseline`）。

### B. 单人长程测试就绪度（本轮最重要）
蹭车测试里沉淀的兜底，大量用 `_passenger_mode()`（= 蹭车 `lobby_hitch` + 跟车 `follow_team`）或 `_hitch_enabled()` 挡住了，**单人刷图 `normal_farm` 用不上**。本地初步盘点如下（mediator.py 共 65 处 `_passenger_mode()`，其中 31 处在 `_tick_main_line`），请逐条核实并分类：
1. **单人仍会"Fail-Closed 停掉整个运行"、蹭车已改成不停机的**：暂停恢复 5 次（约 7564）、胜利页没消失 / 继续游戏重试耗尽（约 14935/14947）、非胜利链路进入存档面板 / 挑战广场（约 14994/15072）、存档面板关闭重试耗尽（约 15051）、传家宝弹窗关闭重试耗尽（约 15202）、未实现的战后页（约 15282）、未验证的战后入口 archive（约 14890/15466）、继续游戏后转场超时（约 15486）、局内退出按钮 / 退出确认超时（约 15756 起）。用户 09-13 已同意"刷图/带队模式下战后面板也不停机"，但一直没实现。
2. **只对蹭车生效的通用监督**：`_hitch_liveness_supervise`（约 10873，只看 `_hitch_enabled()`，连跟车都没有）；战后总预算 300s；战后背包盖住画面时先关背包；面板 natural episode 上限放行；"V 打开没有面板 = 次数不足，不算失败"。
3. **本来就只属于蹭车、不该移植的**：压力转移、座位规则、误开选关页退房、传家宝后 60s / 已获取装备退出（单人的战后规则要用户另定）、蹭车宝物"只拿可共享道具"、L1 循环顺序（蹭车 merchant 起，单人 bond 起）。
4. **已经对所有模式生效的**：细体传家宝模板、MAIN_LINE 选关页顶栏否决、Boss 异常跳过、存档 0.35s、胜利横幅、鼠标停车。

请输出一张表：每项标注"单人长程必须移植 / 建议移植 / 不移植 / 需要用户定规则"，并给出最小改法（例如引入一个"无人值守恢复"判定，替换相应的 `_passenger_mode()`），同时说明单人模式实机至今的验证等级（查 `docs/`、最近的单人 bundle、`tests/` 里的 normal_farm 用例）。

### C. 外发正式版（external-beta）阻塞项
逐条确认现状，并说明是否"必须在外发前解决"：
1. **订阅固定 HTTPS 域名（B1）**：客户端内置和环境里的 `quebec-luis-flooring-kenneth.trycloudflare.com` 已 NXDOMAIN（`src/shuabao/settings.py` 约 121、`src/shuabao/subscription_client.py` 约 47）；`build_release.ps1` 在外发渠道下要求显式 HTTPS 地址。
2. **严格门禁 `--strict-release`**：`disconnect_modal_missing` 为 BLOCKED（缺真实断线弹窗素材）→ 外发必挂。
3. **Authenticode 代码签名**（外发渠道强制）：证书和 secret 是否存在。仓库没有任何 Actions secret。
4. PR #20（看板摘要 / pill / modal 的 XSS 转义，Draft）是否必须先合。
5. 订阅服务端：`ops/production-hardening-0.4-20260913`（compose 原本是 e2e 夹具、端口暴露），账号层 P0（`feat/account-layer-20260913`）。
6. `fix/boss-policy-fallback-layering-20260913`（1b311b3）和 4ed44d4 改的是同一片 Boss 代码：是要重新基于 main 做，还是放弃？

### D. 流程
4ed44d4 / 45c3520 / b66f1ce 是执行 agent 直接提交在本地 main 上的（事后通过 PR #21 补走流程）。评估是否需要在工具 / 文档层面防止再次发生（例如本地 pre-push 钩子、`AGENTS.md` 条款）。

## 4. 证据纪律

- 离线回放、pytest、点击成功都**不能**升级为实机 PASS。实机结论只认 `%TEMP%\shuabao-captures\hitch_lobby_chain_*` 这类 bundle 里的后置条件（本地证据包不在仓库里，你看不到的就写"需本地提供"）。
- 不确定的写"待核实"，不要猜。区分"代码事实"和"推断"。
- 每条发现格式：级别（P0–P3）/ 文件:行号 / 失败场景 / 建议修法 / 是否阻塞单人长程 / 是否阻塞外发。

## 5. 报告结构

1. 结论：**单人长程测试 GO / NO-GO**（附前置条件清单）；**外发 external-beta GO / NO-GO**（附阻塞项清单和负责人：Owner / 本地 / 云端 / VPS）。
2. A–D 各维度的发现。
3. 建议的执行顺序：哪些由本地执行 agent 做，哪些要 Owner 决策。
