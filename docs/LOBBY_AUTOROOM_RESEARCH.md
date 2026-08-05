# 全链路自动化与局外大厅 (L0) 带队建房复刻研究文档

> **项目**：GameScript-Local 1.3.3.3  
> **对比参考**：官方 1.3.3.3 WPF (`GameScript.exe`) 与 `Help.html` / `使用前阅读.html` 说明书。  
> **编写日期**：2026-08-04  

---

## 1. 全链路自动化与 L0 / L1 分层现状

在游戏自动化挂机体系中，完整的全链路自动化划分为两层：

```
┌─────────────────────────────────────────────────────────────┐
│  L0 局外大厅 / 房间层 (Lobby & Room Automation)              │
│  · 自动寻找房间列表 · 自动点击创建房间                       │
│  · 自动输入房间名 (RoomName) / 房间密码 (RoomPassword)       │
│  · 自动等待队员加入 · 自动点击开始游戏                         │
│  · 每局结束后自动退房并重新建房 (NewRoomEveryTimes)          │
└──────────────────────────────┬──────────────────────────────┘
                               │ 游戏加载进入对局
┌──────────────────────────────▼──────────────────────────────┐
│  L1 局内刷图与战斗层 (In-Game Automation)                    │
│  · 自动地图选关 (Stage1—Stage2)                             │
│  · 自动卡组选卡 (Cards) · 自动技能激活 (Skills)               │
│  · 锚点 BOSS 识别 (SGZXBoss / CJBBoss)                      │
│  · 自动找龙珠 (DragonBallCount)                             │
│  · 自动秘境 (AutoSecretRealm) & 局末退出 (QuitGame)          │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 官方 1.3.3.3 WPF 实现逻辑核查

通过分析官方 WPF 包（`GameScript.exe`）及对应说明文档，官方的逻辑如下：

### 2.1 游戏模式语义区别
- **独狼模式 (GameMode = 0)**：
  - 官方说明原文：*“单人 — 自己点击房间开始游戏，如果队友不卡游戏房间，也可以组队使用这个模式。”*
  - **核心机制**：独狼模式下，官方代码**默认不开启**大厅自动建房与设密码逻辑。用户需手动建好房间或点击进入选关页面。
- **带队模式 (GameMode = 1 / 车头)**：
  - 官方说明原文：*“队长 — 会使用房间的自动开始功能，不会主动开始游戏... 支持每局结束后自动建立新房间。”*
  - **核心机制**：`RoomName`、`RoomPassword`、`NewRoomEveryTimes`（每局新房间）仅在**带队模式**下由官方底层 `CreateRoom` 闭包驱动执行。

### 2.2 官方 WPF 反射与方法闭包痕迹
在官方程序内部，包含如下 API 闭包与元素定义：
- `LaunchGame` / `BeginGame`：启动与准备游戏。
- `CreateRoom` / `creatRoomNode`：创建房间、识别建房节点。
- `EntryF1`：房间内自动响应准备/开始。

---

## 3. 本地工程 GameScript-Local 缺口诊断

| 自动化能力 | 官方 WPF 1.3.3.3 | 本地 GameScript-Local 现状 | 补全所需资产与逻辑 |
| :--- | :--- | :--- | :--- |
| **L1 局内选关/战斗** | 完整 | **完整**（选卡、技能、龙珠、Boss 锚点、秘境、退局全支持） | 已稳定运行 |
| **L0 独狼房间开始** | 用户手点 / 或大厅开始 | **支持**（已补全 `LOBBY_ROOM` 双阶 0.65 容错识别与自动点击） | 已添加 `lobby/` 模板 |
| **L0 带队自动建房** | `GameMode=1` 时开启 | **已接入显式状态链** | 可选按钮模板 + 地图/弹窗 ROI；输入框不安全时拒绝盲填 |
| **L0 每局重新建房** | 支持 `NewRoomEveryTimes` | **配置保留，退房重建仍需客户端样本** | 需要房间退出按钮模板与真实回放确认 |

---

## 4. 带队 L0 自动建房的实现与剩余边界

当前 L0 带队自动建房已经接入本地状态机；剩余工作只限于真实客户端样本不足的边界：

### 已实现：场景化检测与状态链

`mediator.py` 现在显式经过：

```text
PLATFORM_MAP → CREATE_ROOM → ROOM_WAITING → ROOM_STARTING
→ STAGE_SELECT → STAGE_STARTING → MAIN_LINE
```

全局蓝色轮廓兜底已删除；地图创建、弹窗确认、房间开始各自有 ROI/模板语义。

### 可选增强：图集资产补充 (`assets/Images/lobby/`)
需要捕获并补充以下 UI 元素的模板截图：
1. `btn_create_room.png` — 平台/大厅“创建房间”按钮
2. `input_room_name.png` — 房间名称输入框焦点图
3. `input_room_pwd.png` — 房间密码输入框焦点图
4. `btn_confirm_create.png` — 建房确认按钮

### 已实现：键盘打字输入交互机制
`gamescript/input/keyboard_mouse.py` 已支持组合键、Unicode 剪贴板粘贴和滚轮，用于在安全识别到两个输入框后输入 `settings.room_name` / `settings.room_password`。

### 已实现：Mediator 状态机扩展 (`CREATE_ROOM`)
`Phase` 已新增 `PLATFORM_MAP`、`CREATE_ROOM`、`ROOM_WAITING`、`ROOM_STARTING`、`STAGE_SELECT`、`STAGE_STARTING`。当前建房链为：
- 地图页点击创建 → 弹窗填名/密码 → 确认 → 等待房间 → 点击开始 → 选关 → 局内验证。
- `NewRoomEveryTimes=True` 的退房重建仍需一张真实房间退出页样本，暂不自动猜退出按钮。

---

## 5. 结论

1. 目前 `GameScript-Local` 项目已完美具备 **L1 局内全流程自动化** 和 **L0 独狼房间开始识别**。
2. 澄清误区：单修改 `Stage1/Stage2` 关卡字段属于 L1 局内选关参数，无法直接驱动 L0 自动建房。
3. 针对 `GameMode=1` 带队车头，地图创建、弹窗输入、确认、房间开始和选关链已接入；每局退房重建仍需真实退出按钮模板。
