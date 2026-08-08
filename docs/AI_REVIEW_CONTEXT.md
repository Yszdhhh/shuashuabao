# AI 审查上下文（游戏背景 / 引擎 / 防作弊 / 项目架构）

> 供云端 AI 审查使用。仓库：https://github.com/Yszdhhh/GameScript-Local.git

## 1. 游戏背景

- **游戏**：`英雄三国`（KK 对战平台的魔兽争霸 3 自定义地图 `重生魔兽刷刷刷`，单人挂机刷图玩法）。
- **玩法**：玩家建房间 → 进图 → 自动清怪推进主线关卡（1-12 ~ 1-24+）→ 选卡/技能/羁绊/宝物强化 → 四挑战（金币/木材/经验/宝物）挂机 → Boss → 存档挑战/秘境 → 退出回房循环。英雄模式（声望挑战）：选阵营（黑锋骑士团等 6 个）→ 难度 1-10 → 开启挑战。
- **资源**：扫荡券（扫荡关卡消耗）、挑战券（开始游戏消耗）、木材（羁绊抽卡）、宝物刷新次数、神器（Q/W/E 槽，固定 180s CD，17 种）。
- **自动化目标**：挂机刷图全流程：建房 → 房间开始 → 选关（滚轮找目标关）→ 英雄模式/普通模式 → 进局自动任务/四挑战/技能选卡 → 进化 → 神器释放 → 战后返回 → 券清空自动进考古模式结束。

## 2. 客户端技术栈（已逆向确认）

| 层 | 技术 |
|---|---|
| KK 对战平台 | Qt 5.15（窗口类 `Qt5152QWindowIcon`），平台 UI 与游戏画面 **CEF/Chromium 内嵌渲染**（`CefBrowserWindow`，游戏窗类名 `pef8ISxqlo3KQSU`） |
| 游戏窗口 | 独立顶层窗口 `英雄三国KK`，建议 1600×900 窗口化 |
| 原版挂机脚本 | .NET 4.8 + ConfuserEx 混淆；输入走 `user32.SetCursorPos` + `SendInput`（`Lan.UIAutomationCore.Input.Mouse`）；图片模板匹配（OpenCvSharp，阈值 0.76/0.83）；清单 `requireAdministrator` |

## 3. 反作弊 / 反自动化机制（实机验证结论）

1. **UIPI（User Interface Privilege Isolation）**：游戏/平台以管理员运行（`requireAdministrator`）。**非提权进程的 SendInput 会被静默丢弃**（API 返回成功但游戏无响应）。这是本项目踩过的最深坑——早期误判为"CEF 反自动化"，实际是 UIPI。修复：面板提权 + 非管理员硬门禁。
2. **CEF 输入**：提权后 SendInput 有效（已实机证明：管理员点击「创建房间」成功弹窗，非管理员同坐标零反应 diff=0）。CEF 本身无额外反自动化。
3. **模板匹配对抗**：游戏 UI 大量相似按钮（选关页"开始游戏" vs 房间页"开始游戏" vs 扫荡/英雄模式/考古模式），需场景级判定（先关卡编号特征，后按钮）。
4. **窗口遮挡**：游戏窗口被编辑器/终端部分覆盖时，点击落到覆盖窗口（SendInput 按屏幕坐标）→ 脚本需 `WindowFromPoint` 遮挡检测。
5. **静止/冻结帧**：弹窗打开后画面静止，帧健康检查需区分"静态可信帧"（放行）与"异常帧"（黑帧/低熵，Fail-Closed）。
6. **无内存修改/网络作弊/驱动注入**：纯视觉 + 系统级输入自动化。

## 4. 项目架构（本地重写版）

```
GameScript-Local/
├─ desktop_app.py          # PySide6 面板（核心配置 + 技能卡片 + 英雄模式 + 开始/停止）
├─ GameScript.spec         # PyInstaller 打包（console=False, uac_admin=True）
├─ build_release.ps1       # 构建脚本（uv venv + PyInstaller → dist/GameScript/GameScript.exe）
├─ src/gamescript/
│  ├─ mediator.py          # 主状态机 ~2300 行：BOOT→建房→房间→选关→英雄→主线→战后→退出
│  │                        # L0: PLATFORM_MAP/CREATE_ROOM/ROOM_WAITING/ROOM_STARTING/STAGE_SELECT/HERO_SETUP
│  │                        # L1: MAIN_LINE（选卡/挑战/进化/神器）/QUIT/NEXT
│  ├─ settings.py           # 配置（类型/范围强制校验 + 自动保存）
│  ├─ monitor_game_over.py  # 静止帧活动监控（未接入主循环）
│  ├─ input/keyboard_mouse.py  # InputExecutor：提权门禁/HWND/前台/遮挡校验 + SendInput
│  ├─ input/emergency_stop.py  # Shift+F12 急停
│  ├─ vision/capture.py    # 窗口捕获/角色选择/帧健康检查/Frame 懒缓存
│  ├─ vision/matcher.py    # 模板匹配（全局模板/尺度缓存、ROI、多尺度）
│  └─ vision/stage_selector.py  # 关卡编号识别/滚动/验证
├─ assets/Images/          # 313 个模板（skills/cards/boss/challenges/lobby 等）
├─ config/scenes.json      # 场景表（优先级/模板/方法映射），validate 130+ 场景
├─ fixtures/               # 实机截图与回放夹具
├─ tests/                  # 76+ 测试（状态机/回放/输入安全/面板/英雄时序）
└─ docs/agent_digs_20260808/  # 原版逆向报告（IL 拆解/坐标/字符串解密）
```

**关键机制**：
- **Fail-Closed**：未知页面/未验证入口 → 零输入停机（ERROR），不盲点
- **遮挡检测**：点击/滚动前 `WindowFromPoint` 验证目标点是游戏窗口
- **静态帧复用**：内容+位置相同帧复用对象，场景缓存命中（性能：detect_context 4.5s → 热态 0.000s）
- **跨局重置**：STAGE_SELECT/MAIN_LINE 进入时清上一局标志（选关/挑战/神器/主动面板）
- **券检测**：扫荡券剩余为 0 → 自动点考古模式 → 结束脚本

## 5. 已知边界（审查时注意）

- 坐标基准 1600×900 窗口（含标题栏偏移 ~30px）；其他分辨率按比例缩放，未全面验证
- 英雄模式面板坐标来自原版 IL 逆向 + 实机，阵营/难度按钮未全部实机校准
- 战后存档/传家宝/秘境/龙珠/Boss 入口目前 Fail-Closed（未实现）
- `monitor_game_over.py` 独立未接入
- 测试用 mock 覆盖输入链，遮挡检测分支未实机全验证
- 模板 313 个，部分来自旧版本 UI（可能过时）

## 6. 合规声明

- 个人本地挂机辅助，纯视觉识别 + 系统输入自动化
- 无内存读写、无网络协议伪造、无驱动注入、无绕过登录/认证
- 需管理员权限仅为满足 UIPI（与游戏同权），非提权攻击
