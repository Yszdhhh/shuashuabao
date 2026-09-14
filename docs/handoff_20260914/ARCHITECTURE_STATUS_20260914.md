# 刷刷宝架构与进度现状（2026-09-14）

面向云端/其他 agent 的"最新进度"入口。审计细节见同目录的 `LOCAL_AUDIT_20260914.md`，上一份交接是 `HITCH_AUDIT_HANDOFF_20260914.md`。

## 1. 版本与入口

| 项 | 值 |
|---|---|
| 唯一主线 | `main`（只允许 PR + merge commit） |
| 本轮 PR 分支 | `fix/hitch-l1-postgame-20260914`（4ed44d4 → b66f1ce → 63d351d 修复 → 34c103f 身份基线 → 文档） |
| 生产代码 | `src/shuabao/`（核心是 `mediator.py`，约 1.6 万行） |
| 实机测试入口 | 桌面「刷刷宝 Live 实机测试.lnk」→ `live_scenario_launcher.ps1 -ProductionSourceSha <HEAD>`，菜单 13 = 蹭车整链 |
| 正式版入口 | 桌面「刷刷宝.lnk」→ `%LOCALAPPDATA%\ShuaBao\launcher` → `current.json` 指向 `app-0.3-dev-<sha>`（由 `build_release.ps1` 构建、签名、安装） |
| 看板 | `ui-v2/`（TS）+ `src/shuabao/shell/dashboard_facade.py`（DashboardFacade v2），跟正式版一起打包 |

## 2. 运行主链路（蹭车 lobby_hitch 模式）

入口是 `Mediator.tick()` → `_tick_impl()`，先做健康门禁（黑帧/低熵/最小化），再按 phase 分派。

```
KK 大厅 ROOM_LIST
  └─ _tick_lobby_hitch：搜房词 → 刷新 → Join → 平台弹窗恢复（lobby_hitch.HitchSearchSM）
ROOM（房间窗口）
  └─ 座位规则：我方成房主 / 坐一楼 / 一楼离开 → 退房并拉黑；Ready
游戏窗口 · 选关大厅（等待 1 号位选难度）→ 零输入，等进局
局内 MAIN_LINE：_tick_main_line
  ├─ 压力转移（画面有按钮就点，没有也不阻塞）→ 自动任务复选框
  ├─ 四挑战右键（金币/木材/经验/宝物）
  ├─ L1 循环 _advance_l1_cycle：merchant → treasure → pickup → public_bag
  │    ├─ 黑商 _maybe_black_merchant（折扣/吞噬丹/杀敌余额）
  │    ├─ 宝物 V：_maybe_open_choice_panel → _ocr_reward_choice（蹭车规则 hitch_treasure_pick：
  │    │        神符/吞噬丹/英雄卡/EX → 刷新 ≤3 次 → 末段兜底选非负面卡）
  │    ├─ 一键拾取 Z
  │    └─ 公共背包 PublicBagFSM（policy/public_bag.py）：B 开包 → 个人包/物品栏右键 → 公共包格 → 关包
  ├─ 聊天条：只在两帧确认后处理，不抢键盘
  └─ 胜负：失败 → 失败链退出；胜利 → 继续游戏 → 战后链
战后链（_post_game_state 分类：POST_VICTORY / ARCHIVE_PANEL / NPC_HUB / HEIRLOOM_DIALOG …）
  ├─ 存档面板：8 张挑战卡 _maybe_click_archive_challenge（绿色"已挑战"是唯一完成证据）
  ├─ 时光之穴 Boss：_maybe_challenge_configured_boss（policy/boss_order.py 顺序定位；
  │        找不到 → 点可见末卡；一张都认不出 → 跳过；任何失败都不停机）
  ├─ 关存档面板 → 广场 NPC_HUB → 点传家宝 NPC → 传家宝 Boss 弹窗 → 选 Boss → 关弹窗
  └─ 传家宝后：右侧已获取装备就退 / 广场满 60s 就退 / 进秘境·团本等失败或胜利页再退
退出 QUIT → NEXT：左上角退出 → 确认 → 回 KK 大厅 → 下一轮
```

兜底机制：
- `_hitch_liveness_supervise`：每个阶段无输入预算到期，先读真实画面校正阶段 / 软复位，再离开，最后 BLOCKED。
- 战后总预算 300 秒（`_HITCH_POSTGAME_HARD_CAP_S`），整局 round deadline。
- 顶栏模式标签 `_top_bar_mode`（存档 = 广场，团本 = raid）：本轮起也用来否决"选关页"误判。

## 3. 各环节验证等级（截至 2026-09-14）

| 环节 | 等级 | 依据 |
|---|---|---|
| 大厅搜房 / 进房 / 座位 / Ready | 实机跑通 | 09-12 起多轮实机 |
| 压力转移 / 自动任务 / 四挑战 | 实机跑通 | 本包每局都有 |
| 黑商 | 实机跑通 | 本包 28 次动作 |
| 宝物 V 选卡 / 刷新 | 实机跑通 | 本包 11 次选中、4 次刷新 |
| 宝物末段兜底（b66f1ce） | 离线真实帧 + 真实 OCR 重放 | f0653/f0662/f0671 → 选"时间停止"；**待实机** |
| 公共背包 | 实机跑通 | 本包 76 次动作，截图确认物品进了公共包格 |
| 存档 8 卡 | 实机跑通 | 第一局 7 张加钥匙卡（已完成），第二局钥匙卡 |
| 时光之穴 Boss | 实机跑通 | BossNotUnlockedLast ×3 |
| 传家宝入口（细体标签，63d351d） | 离线真实帧重放 | f0706–f0708 → OpenHeirloomChallenges；**待实机** |
| 传家宝后 60s / 已获取装备退出 | 离线真实帧重放 | f0353/f0707：14s 不退、61s 退；**待实机** |
| 秘境 / 团本传送后的退出 | 未验证 | 没有真实画面样本 |
| 断线弹窗 | 未验证 | 门禁 frozen_replay `disconnect_modal_missing` = BLOCKED（缺素材） |
| 正式版打包看板 | 见 PR / 本文第 5 节 | 界面只能打开看，实机运行待用户 |

## 4. 并行线 / 未合入

- `fix/boss-policy-fallback-layering-20260913`（1b311b3，工作树 `Worktrees/boss-policy-layering-20260913`）：和 4ed44d4 改的是同一片 Boss 代码，合并时一定会冲突，需要重新基于 main 做。
- PR #20（`fix/launch-summary-escape-20260913`，Draft）：看板摘要 / pill / modal 的 XSS 转义。
- 订阅服务：`ops/production-hardening-0.4-20260913`（订阅仓库），VPS-A 由 Grok 操作；客户端默认订阅地址仍是 trycloudflare 临时域名（已 NXDOMAIN），**正式版的订阅校验依赖这个地址，发布前必须换成固定 HTTPS 域名**。
- 保留待定的旧工作树见 memory「刷刷宝版本收敛」（live-harness-refresh / live-test-boss / live-g0-publicbag-v2 / lobby-hitch-surface-test 等）。

## 5. 已知风险（按优先级）

1. 传家宝入口和 60s 规则的修复只有离线真实帧验证，需要一轮菜单 13 实机回归。
2. `_find_stage_page` 误报多（局内掉落弹窗也会触发），目前靠 HUD 判断和顶栏否决兜着。
3. 粗体传家宝模板在"存档挑战"上能打到 0.573，接近 0.58 阈值（建议阈值改 0.70）。
4. 聊天条在局内常驻打开，原因未定（可能和频繁开 V 的"次数不足"提示有关）。
5. 发布阻塞：订阅固定域名、断线弹窗素材、Authenticode 签名 secret（外部渠道）。
