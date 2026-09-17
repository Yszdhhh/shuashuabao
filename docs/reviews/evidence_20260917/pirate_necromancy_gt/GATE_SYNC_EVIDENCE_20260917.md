# Gate 1 / Gate 2 同步与实机预检审计报告 (2026-09-17)

## 1. 基础 Refs 与合流审计

- **起始 Test HEAD**: `ab0c80eced5845aa72ad3d65a2b33ee5493ef214`
- **正式生产 Candidate**: `origin/fix/solo-live-regression-20260915` (`bbf2de0e749095ee8dcef656a57b1eef3371e4fa`)
- **合流方式**: `git merge --no-ff origin/fix/solo-live-regression-20260915`
- **合流 Commit SHA**: `f3f4afc15db5cf26de387cba19dd8e12efe319ce`
- **Ancestor 关系核验证实**: 
  `git merge-base --is-ancestor bbf2de0e749095ee8dcef656a57b1eef3371e4fa HEAD` -> **True**
- **权威版本采纳规则**:
  冲突严格限定在 `src/shuabao/vision/capture.py` 的 HWND / EnumWindows FFI 重叠区域。按照指令规范，完全以生产基线 `bbf2de0` 的 `capture.py` 与 `test_capture_hwnd_ffi.py` 为权威版本。
- **Diff 审计**:
  - `git diff bbf2de0 HEAD -- src/shuabao/vision/capture.py` -> **0 diff** (完全一致)
  - `git diff bbf2de0 HEAD -- src/shuabao/mediator.py` -> **0 diff** (完全一致)
  - `git diff bbf2de0 HEAD -- src/shuabao/runtime_mediator.py` -> **0 diff** (完全一致)
  - `src/shuabao/` 下对比生产 `bbf2de0` 的改动严格收敛在 4 个测试接线文件：
    1. `src/shuabao/choice_policy.py`
    2. `src/shuabao/settings.py`
    3. `src/shuabao/shell/main_window.py`
    4. `src/shuabao/shell/test_profiles.py`

---

## 2. 聚焦离线回归套件 (Focused Offline Regression)

执行环境：`G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe`

测试执行统计：**219 passed, 0 failed, 0 skipped** (无任何预期妥协，无 Harness rebaseline)

| 测试文件 / 模块 | 用例数 | 结果 | 涵盖功能与回归目标 |
| :--- | :---: | :---: | :--- |
| `tests/test_capture_hwnd_ffi.py` | 4 | **PASS** | HWND FFI 64位句柄枚举与 callback 类型兼容性 |
| `tests/test_p1_scheduler_and_f4_20260916.py` | 20 | **PASS** | P1 调度器与 F4 状态机 |
| `tests/test_p1_multiround_and_room_form_20260916.py` | 12 | **PASS** | 多轮循环与建房表单交互 |
| `tests/test_p1_blockers_reproduction_20260916.py` | 20 | **PASS** | 阻断问题复现保护 |
| `tests/test_s0_hitch_failure_exit.py` | 25 | **PASS** | S0 挂起失败与安全退出 |
| `tests/test_live_run_205044_regressions.py` | 21 | **PASS** | 实机回归用例验证 |
| `tests/test_l1_cycle_recheck_merchant.py` | 60 | **PASS** | L1 循环复检与神秘商人逻辑 |
| `tests/test_public_bag_transfer.py` | 56 | **PASS** | 公共背包转移机制 |
| `tests/test_desktop_app.py -k test_profile_replaces_stale_shell_state` | 1 | **PASS** | 测试方案替换陈旧状态 |
| `tools/check_pirate_necromancy_profile.py` | 合约 | **PASS** | 离线契约验证 (`offline_contract: PASS`) |

---

## 3. HWND Blocker 修复核验与环境隔离分析

- **前次 Blocker 复盘**:
  前次预检及 `test_capture_hwnd_ffi.py` 在 64 位 Windows 下因 `ctypes.wintypes.LPARAM` 产生有符号/无符号截断溢出 (`OverflowError: int too long to convert`)。
- **修复确认**:
  正式生产提交 `f1c4e8d + bbf2de0` 将 `WNDENUMPROC` 回调参数及 EnumWindows 封装显式声明为 `ctypes.c_ssize_t` 与兼容指针。经核验，在 Windows 交互桌面下可正常枚举 360+ 窗口，无任何异常。
- **环境隔离发现**:
  在后台沙箱代理（`exebox-...`）子进程中，默认分配在不可见桌面，调用 `OpenDesktopW('Default')` + `SetThreadDesktop` 即可安全连接交互桌面，完全兼容实机窗口探测。

---

## 4. 桌面测试看板 (Test Dashboard) 交付落地

针对【无需命令行拼装，桌面直接可见可点】的核心交付要求，完成了专用桌面看板落地：

1. **测试看板脚本**:
   - `tools/test_dashboard.py`：基于 PySide6 构建独立测试看板 GUI。
   - 具备完整 Worktree HEAD / 基线 Production Candidate SHA / Python 解释器 / 真实 `shuabao` 导入路径的自校验显示，防止环境混淆。
   - 明确展示当前生效配置：`海盗+亡灵机制GT`（关卡 1-12，循环 1 局，`auto_secret_realm=true`，`auto_devour_dan=false`）。
   - 提供显式交互按钮：
     - **一键预检 (ZERO-INPUT)**：执行非侵入式探测（检查 KK 平台、游戏窗口、OCR 模型与环境）。
     - **开始测试 (Live GT)**：通过前置安全阻断守卫，确认状态合规后拉起实机测试链路。
     - **打开完整配置看板**：直接唤起嵌入式完整 Web Shell 界面（已内置 `ui-v2/dist` 资源）。
2. **桌面快捷方式配置**:
   - `C:\Users\10639\Desktop\刷刷宝 测试看板.lnk` -> 指向 `tools/test_dashboard.py`，工作目录为当前测试 Worktree。
   - `C:\Users\10639\Desktop\刷刷宝 看板预览.lnk` -> 同步更新为指向测试看板。
   - **生产正式入口保护**: `刷刷宝.lnk` 与 `刷刷宝 Live 实机测试.lnk` **保持完全未修改**，绝不干扰正式生产运行。

---

## 5. ZERO-INPUT 预检与实机测试会话状态

- **预检执行结论**: `BLOCKED_PRECONDITION`
- **详细阻断原因**:
  1. KK 官方对战平台进程存在（PID: 42576, HWND: 10551702），但处于**【最小化】**状态（坐标 `[-32000, -32000]`）。
  2. 尚未检测到【英雄三国】游戏窗口（`Game_x64h.exe` 未在运行）。
- **执行安全策略**:
  严格遵守 `BLOCKED_PRECONDITION + ZERO INPUT` 规范：
  - 不强行模拟键盘鼠标去还原最小化窗口；
  - 零输入拦截，绝不盲目发送任何点击或按键；
- **Session A / B 状态**:
  - Session A（1-12 全关卡）: **NOT_RUN** (`BLOCKED_PRECONDITION`)
  - Session B（手工 GT 观测）: **NOT_RUN** (`BLOCKED_PRECONDITION`)
- **当前状态等级**: **READY-TO-TEST**
  人工操作员将 KK 平台与游戏窗口在桌面恢复显示后，双击桌面【刷刷宝 测试看板】点击【开始测试】即可一键无缝点火。
