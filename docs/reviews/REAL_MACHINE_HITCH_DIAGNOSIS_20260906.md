# 刷刷宝实机 Hitch 组车房间判定死锁与遮挡排查审查报告

**日期**: 2026-09-06  
**分支**: `trial-merge`  
**基线 Commit**: `30d8a0ff9b70e8cc5790e1a629ff5dc2808408f5`  
**最新 Commit**: `4b63928dc0211f5030b9b7d0d7f58d768886e6ed`  
**最新构建包**: `app-0.3-dev-4b63928dc021`  
**云端中台状态**: `approved` (source_sha: `4b63928...`, release_manifest: `ce7899...`)

---

## 一、生产实机阻断现场还原与失败日志

### 现场 1：退房后置检查死锁（持续 54 步）
- **现象**：脚本在房间内成功点击退出房间与退出确认后，持续 54 steps 卡在：
  ```text
  [L0] hitch 已点击退出，等待大厅列表且无房间实体控件（零输入）：lobby_visible=True, tangible_room=True
  ```
- **物理现场**：KK 平台已经回到大厅，但因为大厅底部存在通用的“快速加入 / 快速匹配”等蓝色几何按钮，被通用匹配函数 `_hitch_room_action_control` 识别为房间控件，导致 `tangible_room=True`，后置退出等待无法重置。

### 现场 2：大厅非房间列表页（任务/排行榜）误判为在房内
- **现象**：当大厅停留在“任务”或“排行榜”标签页时，每秒持续打印：
  ```text
  [med] capture tick 1332x945 @(519,40) phase=ROOM_WAITING ...
  [L0] hitch 一楼条件不符(leave_host_not_floor_one)，但退出按钮未确认
  ```
- **物理现场**：代码脱离了物理窗口拓扑判断，仅靠画面局部蓝色色块断定 `in_room=True`；误以为在房内后去检查房主红字标签失败，大厅页面上又没有退出房间按钮，导致陷入死循环，根本不走“点击切换房间列表 Tab”分支。

### 现场 3：输入被拒执（输入守卫遮挡保护）
- **最新实机日志**：
  ```text
  [med] search_box text='4' @ (1746, 331) (HitchSearchBox)
  [input] click (1746, 331) CANCELLED: Click point (1746,331) is covered by another window (hwnd=197526).
  Move editors/terminals off the game window or bring the game to front.
  [L0] hitch 搜索词 '4' 输入被拒绝，保持未搜索状态
  ```
- **物理现场**：脚本已经完全脱离之前的死锁，准确识别并锁定了搜索框 `(1746, 331)`。但在准备模拟点击时，由于桌面上的其他窗口（如终端/浏览器）覆盖在该坐标之上，触发了 `InputExecutor` 的遮挡保护安全哨兵，将输入取消。

---

## 二、物理根因分析与架构断层

1. **窗口拓扑硬门禁缺失**：
   - 在 KK 平台中，大厅主界面与独立的房间子窗口是两个不同的顶级 HWND。
   - 当系统中只有 **1 个 KK HWND** 时，物理上绝不可能处于独立房间内。
   - 之前代码在 `_tick_lobby_hitch` 和退出等待分支中，仅凭单帧画面局部的蓝色像素来推断 `in_room` 和 `tangible_room`，导致大厅底部的任何蓝色按钮都会诱发房间误判。
2. **退出等待分支权限未对齐**：
   - 之前仅在 `_tick_lobby_hitch` 开头收紧了 `in_room`，但退房后置等待分支（第 7427 行）的 `tangible_room = room_start is not None or self._hitch_tangible_room_evidence(frame)` 没有收紧拓扑门禁，依然受大厅控件误匹配影响。
3. **Windows UIPI 权限隔离**：
   - KK 平台是管理员权限运行，如果运行脚本的进程未提权，发出的键盘鼠标注入会被 Windows UIPI 静默丢弃，必须确保由提权的已安装 EXE 执行。

---

## 三、代码改动与演进记录

### 1. Commit `30d8a0f`
- 收紧 `_hitch_tangible_room_evidence(frame)`，仅允许 `room_start`, `room_ready`, `readyBtn`, `room_cancel_ready`, `room_exit_btn` 作为房间专属证据，坚决剔除通用蓝色几何块回退。

### 2. Commit `35665d9` & `b3c5822`
- 将 `_capture_candidates` 作为物理拓扑硬门禁：
  - 1 个 KK HWND：`in_room = False`（物理上绝不在独立房间内）；
  - $\ge 2$ 个 KK HWND：仅表示房间可能存在，仍需房间专属证据；
  - 纯单测无窗口枚举时（`_capture_candidates == 0`）放行单测 mock。
- 收紧 `_capture_best` 中的 `hitch_join_probe`，选择 child 必须依赖房间专属证据，不再依据泛化蓝色几何。

### 3. Commit `4b63928`（本次修复最终闭环）
- 彻底修补第 7427 行漏洞：将 `_hitch_floor_exit_pending` 分支中的 `tangible_room` 同样收紧至 `topology_possible and bool(...)`：
  ```python
  tangible_room = topology_possible and bool(
      room_start is not None or self._hitch_tangible_room_evidence(frame)
  )
  ```
  退房后只要系统只剩 1 个 KK 窗口，`tangible_room` 物理强制为 `False`，瞬间解除死锁。

---

## 四、测试与发版门禁验证证据

1. **针对性回归测试（24/24 PASS）**：
   - `pytest tests/test_hitch_l0_and_hud_fixes.py`：**24 passed in 3.24s**
   - 覆盖场景：
     - 1 KK + 真实大厅任务页 + Quick Join $\rightarrow$ `in_room=False`，成功触发切换房间列表 Tab；
     - 2 KK + 真实房间页 + room_start/ready $\rightarrow$ `in_room=True`；
     - 2 KK（parent 含有 Quick Join，child 含有房间控件）$\rightarrow$ `_capture_best` 强制选择 child；
     - `_hitch_floor_exit_pending` 在面对包含 Quick Join 的大厅帧时 100% 清除 pending 并推进。
2. **全量发版门禁（4/4 PASS）**：
   - `pytest`：**1561 passed**
   - `frozen_replay`：**PASS**
   - `scene_templates`：**PASS**
   - `contract`：**PASS**
3. **安装包身份核验**：
   - 路径：`C:\Users\10639\AppData\Local\ShuaBao\app-0.3-dev-4b63928dc021\ShuaBao.exe`
   - `current.json`：指向 `app-0.3-dev-4b63928dc021`（commit `4b63928`）
   - 云端审核接口返回：`status='approved'`
