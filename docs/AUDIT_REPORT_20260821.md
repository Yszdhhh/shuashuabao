# 刷刷宝 2026-08-21 稳定性与长线程保活架构审查报告（Audit Report）

## 一、 核心架构哲学转变：从「死板门禁（Fail-Closed）」到「长线程顺畅吞吐优先（Fail-Forward）」

### 1. 挂机业务核心痛点
- **根本矛盾**：此前设计过度追求微观精确匹配（如 Sobel 边缘积分硬卡 > 900、单帧卡名未识别强行等待超时退出），导致实机录屏长测（`20260821_101935.mp4`）多次发生“原地罚站”。
- **工程定调**：
  > **挂机脚本的第一生命线是长线程稳定自愈与高吞吐量（Throughput & Liveness），而非死板的 100% 选卡精度。即使遇到偶发未知卡牌，按最高品质色盲选或关闭面板继续刷怪打 Boss，也远好于原地阻塞 6 小时。**

---

## 二、 本次提交核心改动明细（Changes Summary）

### 1. 弹窗选择 3 秒强制降级推进（Fail-Forward Choice）
- **文件**：`src/shuabao/mediator.py` (`_handle_panel_state_machine`)
- **逻辑**：
  - 若 3 秒内 OCR/模板未能提取合法卡名，自动触发品质降级（`_rarity_choice`：红UR > 橙SSR > 紫SR > 蓝R）；
  - 若品质色仍未检出，触发兜底关闭按钮或点击右侧安全区域关闭弹窗，强制步进主循环，100% 杜绝面板死锁。

### 2. 英雄进化弹窗自适应与品质保底
- **文件**：`src/shuabao/mediator.py` (`_find_evolution_choice`)
- **证据帧**：`docs/evidence_20260821/modal_at_250s.png`, `card1_250s.png`, `card2_250s.png`
- **逻辑**：
  - 边缘积分自适应阈值放宽至 `350/300`，完美覆盖 2 卡（SSR/SR）与 3 卡进化弹窗；
  - 解除对底部特定锚点的强依赖；
  - 进化优先级逻辑：`UR(红) > SSR(橙) > 未知进化(3.5) > SR(紫) > R(蓝)`；开启 `evolve_mystic_priority` 时未知进化置顶。

### 3. 15 秒主线活性看门狗（Proactive Liveness Watchdog）
- **文件**：`src/shuabao/mediator.py` (`_tick_main_line`)
- **逻辑**：
  - 若主线持续 15 秒无任何有效动作（Idle 超时），不再抛出 Fatal Error，而是主动向游戏发送 `ESC` 键关闭异常覆盖层，并强行步进轮转（`_advance_l1_cycle`），确保战斗与拾取不中断。

### 4. 物品栏英雄卡与装备 1 号位升级连贯执行
- **文件**：`src/shuabao/mediator.py` (`_maybe_upgrade_equipment`, `_maybe_use_inventory_item`)
- **证据帧**：`docs/evidence_20260821/inv_250s.png`, `inv_270s.png`
- **逻辑**：
  - 物品栏英雄卡直接通过 6 格 ROI 像素特征触发使用，不再受限于底部锚点校验；
  - 装备 1 号位右键升级采用独立调度冷却，与物品使用解耦并行。

### 5. 黑商吞噬丹秒买保障
- **文件**：`src/shuabao/mediator.py` (`_maybe_black_merchant`)
- **证据帧**：`docs/evidence_20260821/merchant_180s.png`, `bond_bar_180s.png`
- **逻辑**：
  - 羁绊栏只要存在非空羁绊，黑商遇到吞噬丹（`danGif`）最高优先级买入并使用。

### 6. 发育主线优先权重调度
- **文件**：`src/shuabao/mediator.py` (`_L1_CYCLE_ORDER`)
- **逻辑**：
  - 调整主循环顺序为 `("bond", "skill", "bond", "skill", "treasure", "equipment", "evolve", "pickup", "merchant", "artifact")`，确保局内木头优先用于成型核心羁绊与技能。

### 7. 三级窗口前台置顶调度与 HUD 自由拖拽
- **文件**：`src/shuabao/vision/capture.py`, `src/shuabao/shell/overlay_hud.py`
- **逻辑**：
  - 局内有英雄三国进程：**绝对优先保持英雄三国在最前台**；
  - 仅有 KK 平台且大厅+房间并存：**小窗口（房间）优先置顶**；
  - HUD 仅首次捕获停靠，支持玩家任意拖拽停放，不再每帧晃动。

### 8. 看板向导 UI 纯工具化去噪与专属品牌整合
- **文件**：`src/shuabao/shell/wizard_dialog.py`, `theme_styles.py`, `desktop_app.py`
- **逻辑**：
  - 第一页模式选项：单人 / 多人（全自动蹭车、跟车、带人）；
  - 剥离所有主观攻略词汇（如 0 氪下限高、KK夙愿等），仅保留流派名称与 4 技能清单；
  - 原图完整黑底高分辨率多层 ICO 接入窗口、向导与桌面快捷方式。

---

## 三、 实机证据索引（Evidence Artifacts）

| 证据文件名 | 采样时间/场景 | 证明与审查要点 |
| :--- | :--- | :--- |
| `docs/evidence_20260821/frame_240s.png` | 240s 局内底部 HUD | 金色点击进化按钮出现坐标与特征 |
| `docs/evidence_20260821/modal_at_250s.png` | 250s 进化弹窗 | 双卡英雄选择弹窗结构（SSR+SR） |
| `docs/evidence_20260821/card1_250s.png` | 250s 进化卡片 1 | 左侧 SSR 英雄卡边界与色相分布 |
| `docs/evidence_20260821/card2_250s.png` | 250s 进化卡片 2 | 右侧 SR 英雄卡边界与色相分布 |
| `docs/evidence_20260821/inv_250s.png` | 250s 物品栏 | 物品栏第 3 格英雄卡道具位置 |
| `docs/evidence_20260821/inv_270s.png` | 270s 物品栏 | 物品栏第 1 格装备占用与右键升级区域 |
| `docs/evidence_20260821/merchant_180s.png` | 180s 黑商区域 | 黑商货架吞噬丹与刷新按钮位置 |
| `docs/evidence_20260821/bond_bar_180s.png` | 180s 羁绊栏 | 局内已激活羁绊栏占用特征 |

---

## 四、 自动化回归测试结果

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0
collected 163 items

tests/test_choice_policy.py ............................................ [ 26%]
....................................................................     [ 68%]
tests/test_l1_cycle_recheck_merchant.py ..............................   [ 87%]
tests/test_s0_safety_state_machine.py .....................              [100%]

============================= 163 passed in 7.24s =============================
```
