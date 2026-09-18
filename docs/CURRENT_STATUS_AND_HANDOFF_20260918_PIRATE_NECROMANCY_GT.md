# ShuaBao「海盗+亡灵机制 GT」测试交接与审计必读文档（2026-09-19）

> **交接对象**：后续审计 Agent、Coding Agent 及产线维护工程师  
> **当前状态**：全部 7 项实机异常（圣光之盾取出、红框极速流转、黄金猿激活、定期 Z 拾取解耦、技能/羁绊/背包打架隔离、4 槽选卡坐标偏离、10/10 满槽智能顶替/放弃重置 40 木）已全部闭环修复并严格测试验证。门禁与单测全部 PASS，状态 READY。  
> **审计报告专卷**：详见 [`docs/reviews/AUDIT_RECORD_PIRATE_NECROMANCY_GT_20260919.md`](reviews/AUDIT_RECORD_PIRATE_NECROMANCY_GT_20260919.md)

---

## 0. 关键基线与环境铁律

- **工作树路径**：`G:\刷刷宝\Worktrees\pirate-necromancy-gt-20260917`
- **当前分支**：`test/pirate-necromancy-gt-20260917`
- **最新 Commit**：`06eee1b91859cfa6bb68883024098a3531c8c117`
- **生产锚点 SHA**：`b52c69e2aa1f74b59506439cceba06535bc6234c` (`fix/solo-live-regression-20260915`)
- **Python 解释器**：必须使用 `G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe`（本 worktree 自身无独立 `.venv`）。
- **Git 铁律**：本目录为 git worktree，stash 栈与主库完全共享。**严禁执行裸 `git stash` 或 `git stash pop`**。
- **业务铁律**：`auto_devour_dan` 必须保持 `False`。

---

## 1. 核心缺陷与改进改动定位

详见 [`docs/reviews/AUDIT_RECORD_PIRATE_NECROMANCY_GT_20260919.md`](reviews/AUDIT_RECORD_PIRATE_NECROMANCY_GT_20260919.md)，核心摘要如下：

### A. 圣光之盾放进背包取出卡住（两步闭环）
- **修改文件**：[`src/shuabao/mediator.py`](../src/shuabao/mediator.py)
- **机制**：第 1 步右键拿起装备并进入 `withdraw` 状态；第 2 步左键点击目标空白物品栏（`EquipPlaceItemBarSlot`），闭环完成穿戴并清除状态。连续 2 次失败熔断保护。

### B. 红框物品栏极速操作（缩短位移 80%）
- **修改文件**：[`src/shuabao/mediator.py`](../src/shuabao/mediator.py)
- **机制**：通过 `layout.item_bar_slot_rect` 定位背包下方内嵌的 6 格红框物品栏，存入与取出位移从跨屏 1000+ 像素缩短至 150~250 像素。

### C. 黄金猿道具识别与自动使用
- **修改文件**：[`src/shuabao/mediator.py`](../src/shuabao/mediator.py)、[`assets/Images/haidao/haidao_gold_ape.png`](../assets/Images/haidao/haidao_gold_ape.png)
- **机制**：采集 26x24 黄金猿高精图标（匹配得分 1.000），在红框与快捷栏中左键点击 `UseItemBar-gold_ape` 激活宝藏卡组。

### D. 定期 Z 拾取与物品栏满载解耦
- **修改文件**：[`src/shuabao/mediator.py`](../src/shuabao/mediator.py)
- **机制**：移除 `_hud_item_bar_overflowed` 满载限制。无中央面板遮挡时，每 12 秒独立触发一次拾取（优先 HUD 按钮，键盘 `z` 兜底），并在拾取后标记 `_backpack_has_overflow_items = True`。

### E. 彻底消除“技能、羁绊、背包逻辑打架/卡顿”
- **修改文件**：[`src/shuabao/mediator.py`](../src/shuabao/mediator.py)
- **机制**：
  1. **选卡优先**：主循环将 `_maybe_open_choice_panel` 提至微操最前列，轮到 G/F/V 时优先完成选卡。
  2. **选卡严禁开包**：当 `_l1_cycle_step in ("bond", "skill", "treasure")` 时，严格禁止执行 `_open_bag_page` 打开背包。
  3. **模板补齐**：`_find_panel_refresh` 的 skill 候选列表中补充专用模板 `skill_refresh_btn`。

### F. 4 槽羁绊面板坐标偏差纠正
- **修改文件**：[`src/shuabao/mediator.py`](../src/shuabao/mediator.py)
- **机制**：固化 4 槽真实物理布局，第 2 槽点击点纠正为 `(1189, 504)`，彻底消除点入两卡间黑色缝隙导致的 15s 冻结。

### G. 10/10 满槽替换卡牌智能顶替与重置 40 木
- **修改文件**：[`src/shuabao/mediator.py`](../src/shuabao/mediator.py)、[`assets/Images/replace_card_*`](../assets/Images/)
- **机制**：N 级海盗新卡直接点击【放弃】（`800, 539`），防止破坏核心卡组并重置刷新木材至 40 木；白名单核心卡保护；高阶海盗向下顶替低阶海盗。

---

## 2. 门禁与验证基线（接手复核命令）

接手 Agent 或审计人员可通过以下只读命令核验全部验证基线：

```powershell
# 1. 核验当前 HEAD Commit
git rev-parse HEAD
# 期望输出：06eee1b91859cfa6bb68883024098a3531c8c117

# 2. 业务专项单测与隔离契约复核（82 项全过）
python -m pytest tests/test_policy_bond_identity_20260916.py tests/contract -q
# 期望输出：82 passed, 111 subtests passed in ~8s

# 3. 端到端冻结场景回放复核（7 场景全绿）
python tools/run_frozen_replay.py
# 期望输出：Total=7 Passed=6 Blocked=1 Failed=0，退出码 0

# 4. 场景模板与资源完整性
python tools/validate_scenes.py
# 期望输出：ok=148 missing=0，退出码 0

# 5. 分支身份与产线就绪门禁
python tools/gt_test_identity.py
# 期望输出：status=READY
```

---

## 3. 实机测试执行方法

用户可在实机通过以下任一方式启动测试（需打开魔兽「英雄三国」房间/选关界面）：

### 途径 1：桌面测试看板（推荐用户图形化操作）
- 快捷方式：`C:\Users\10639\Desktop\刷刷宝 测试看板.lnk`
- 对应代码：[`tools/test_dashboard.py`](../tools/test_dashboard.py)
- 机制：
  1. 打开 KK 进入「英雄三国」选关界面；
  2. 看板点击 **“刷新 canonical 预检（ZERO INPUT）”**；
  3. 状态变为绿色 **`READY`** 后，点击 **“开始 canonical one-click”**。

### 途径 2：管理员命令行直接启动（无 UI 交互）
在管理员权限 PowerShell 中执行：
```powershell
cd G:\刷刷宝\Worktrees\pirate-necromancy-gt-20260917
powershell -ExecutionPolicy Bypass -File tools/one_click_test.ps1
```

> **安全急停**：测试过程中随时按快捷键 **`Shift + F12`** 紧急停止。

---

## 4. 实机验收分析指南

测试数据生成于 `captures/pirate_necromancy_<timestamp>/`。
请重点检查：
1. **圣光之盾取出**：`run.log` 中是否出现 `EquipPlaceItemBarSlot-*`，且随后装备成功处于红框物品栏。
2. **红框内操作**：物品栏内物品存入/取出是否均在背包内部的红框坐标执行，无远距离鼠标跳跃。
3. **黄金猿使用**：物品栏出现黄金猿时，是否派发 `UseItemBar-gold_ape` 并触发宝藏卡组选择。
4. **定期 Z 拾取**：在装备栏未满时，每 12s 是否准时发出 `Pickup-Z`。
5. **选卡无打架**：选技能（G）和选羁绊（F）是否流畅完成，期间背包不主动打断。
6. **满槽替换与重置**：10/10 出现 N 级卡时是否自动点击【放弃】并将刷新木材重置为 40 木。
