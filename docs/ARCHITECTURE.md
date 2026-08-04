# GameScript 1.3.3.3 — 架构恢复文档

> 从现有 `GameScript.exe` + 配置/帮助/Images 元数据还原，供源码丢失后重建用。  
> 生成时间：2026-08-03 · 版本痕迹：`1.3.3.3+775839faf887b6a40e80114f48b1686d5717000f`

---

## 1. 一句话定位

**WPF 桌面挂机助手**：锁定游戏窗口 → OpenCV 模板匹配 `Images/` → 键鼠/快捷键驱动 → 以 `LoopAction` 状态机循环跑关。

技术栈：**.NET Framework 4.8 + WPF + HandyControl + CommunityToolkit.Mvvm + OpenCvSharp + Lan.UIAutomation(FlaUI 系) + H.InputSimulator + Costura 内嵌依赖**。

---

## 2. 仓库/发布包布局（当前磁盘）

```
1.3.3.3/
├── GameScript.exe              # 主程序（Costura 打进依赖，~45MB）
├── GameScript.exe.config       # 默认 userSettings（部分）
├── GameScript.pdb              # 符号/SourceLink 痕迹
├── Help.html                   # 使用说明 v2.0
├── 使用前阅读.html               # 环境/模式完整说明 v1.8
├── Images/                     # 模板库（识别资产，自研重建的核心）
│   ├── *.png                   # 通用 UI：开始、失败、刷新、龙珠…
│   ├── boss/                   # 主线 Boss 图（01–51）
│   ├── chuanjiaobao/           # 传家宝 Boss
│   ├── cards/                  # 卡牌/属性选择
│   └── skills/                 # 技能图标（jq,pg 等短码）
├── dll/x64/                    # 原生 OpenCV 运行时
└── _recovery/                  # 本次恢复产物（本目录）
```

运行时设置不只在 `.config`：`Settings` 继承 `JsonSettingsBase`，会读写 **JSON 设置文件**（`GetSettingsFilePath` / `Save` / `Reload`）。

---

## 3. 分层架构

```
┌─────────────────────────────────────────────────────────┐
│  UI 层  GameScript.App / MainWindow (WPF + HandyControl) │
│  - 环境检测、机器码展示、证书选择、模式/参数面板、启动/停止   │
└───────────────────────────┬─────────────────────────────┘
                            │ Settings.Default
┌───────────────────────────▼─────────────────────────────┐
│  任务层  GameScript.Jobs                                  │
│  - AutoJob.Run()  主循环                                  │
│  - LongzhuJob : AutoJob  龙珠专项                           │
│  - CardGroup / Skill  卡组与技能数据                         │
└───────────────────────────┬─────────────────────────────┘
                            │ CaptureWin / PressKey / findDic
┌───────────────────────────▼─────────────────────────────┐
│  感知与执行                                                │
│  - OpenCvSharp  模板匹配（targetImage / findDic / findIdx） │
│  - Lan.UIAutomation  找窗口/控件                             │
│  - H.InputSimulator + MouseKeyHook  键鼠 + 全局热键         │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│  横切                                                     │
│  - Models.Settings / JsonSettingsBase  持久化配置           │
│  - Models.CertClient + Standard.Licensing + DeviceId       │
│  - SignalR Client  证书/通知 Hub（StartAsync/StopAsync）     │
│  - NetworkTimeHelper  NTP 时间                              │
│  - PowerHelper  防息屏/睡眠                                 │
│  - EnvironmentUtils  会话/管理员环境                         │
│  - Costura.AssemblyLoader  内嵌 DLL 加载                     │
└─────────────────────────────────────────────────────────┘
```

---

## 4. 可读命名空间与类型（未混淆/部分保留）

| 命名空间 | 类型 | 职责 |
|----------|------|------|
| `GameScript` | `App` | 启动入口 `OnStartup` |
| `GameScript` | `MainWindow` | 主 UI、模式开关绑定 |
| `GameScript` | `MutexHelper` | 单实例 |
| `GameScript.Jobs` | `AutoJob` | 主状态机循环 |
| `GameScript.Jobs` | `LongzhuJob` | 继承 AutoJob，龙珠逻辑 |
| `GameScript.Jobs` | `CardGroup` | 卡组 |
| `GameScript.Models` | `Settings` | 全部业务参数 |
| `GameScript.Models` | `JsonSettingsBase` | JSON 配置基类 |
| `GameScript.Models` | `Skill` | `GetAllSkill` / `GetBoss` / `GetAllCardGroups` |
| `GameScript.Models` | `CertClient` | 证书 + SignalR Hub |
| `GameScript.Models` | `PowerHelper` | 电源 |
| `GameScript.Models` | `EnvironmentUtils` | 环境 |
| `GameScript.Extensions` | `LoopAction` | `Continue` / `Break` |
| `GameScript.Extensions` | `NetworkTimeHelper` | 网络时间 |
| `GameScript.Extensions` | `ListBoxHelper` | 多选绑定 |
| `Costura` | `AssemblyLoader` | 依赖内嵌 |

大量类型/方法仍为随机名（混淆），但 **业务骨架名保留**，足够重建状态机边界。

---

## 5. 行为框架：`LoopAction` 状态机

完整对照见 **`docs/SCENES.md`** / **`config/scenes.json`**。

闭包还原的方法链：

```
LaunchGame / BeginGame → CreateRoom → EntryF1 → SelectStage
→ FindAllMatchImages / FindCardImages / FindNode(s)WithTimeOut
→ CloseCardPanel / CloseSkillPanel → ChangeMainLineStatus
→ ClickOKBtn → MonitorGameOver → QuitGame → Run
```

```csharp
// 语义还原（非源码照抄）
enum LoopAction { Continue, Break }
// SelectStage(Stage1Rec, userStage1)
// CloseCardPanel(strictMode) / CloseSkillPanel(strictMode)
// QuitGame(gameCount) / CaptureWin / PressKey
```

**推荐重建模型：**

```
while (running) {
  frame = CaptureGameWindow()
  state = Classify(frame)          // 用模板命中集合判定场景
  action = Transition(state, settings)
  if (action == Break) break
  Execute(action)                  // 点击模板坐标 / 按键
  Sleep(settings.tick)
}
```

`AutoJob` 字段痕迹：

- `GameWindow` / `gameWindows` — 目标窗口  
- `findDic` / `findIdx` / `targetImage` — 找图缓存与当前目标  
- `gameMode` / `woodMode` / `strictMode` — 模式  
- `cardGroup` / `cardNumber` / `creatRoomNode` — 卡组与建房  
- `anchorBossName` / `sgzxBossName` / `infiniteBoss` — Boss 选择  

`MainWindow` UI 痕迹：

- `machineCode` TextBox  
- `woodMode` / `infiniteBoss` / `multiGame` ComboBoxItem  
- `autoReputation` ToggleButton + `reputationPanel`  

---

## 6. 识别框架

### 6.1 资产组织

| 目录 | 数量约 | 用途 |
|------|--------|------|
| `Images/` 根 | ~136 | 流程 UI：开始、失败、刷新、存档、龙珠、秘境、关闭… |
| `Images/boss/` | 51 | 主线 Boss 点选/识别 |
| `Images/chuanjiaobao/` | 17 | 传家宝 Boss |
| `Images/cards/` | 36 | 卡牌/属性 |
| `Images/skills/` | 16 | 技能（短码如 `jq`,`pg`） |

`Settings.Skills` 默认示例：`jq,pg`（与 skills 文件名对应）。

### 6.2 运行约束（来自帮助文档，写死进环境检测）

- 单屏  
- 系统缩放 **100%**  
- 游戏 **窗口化 1600×900**  
- 关闭「鼠标固定在游戏画面」  
- 赌木模式强制 **OSK**  
- 紧急停止：**Shift+F12**  

### 6.3 识别管线（重建约定）

1. 用 UIAutomation / 窗口标题类名拿到 `GameWindow` 矩形  
2. `CaptureWin` 截窗口客户区  
3. OpenCV `matchTemplate` 对候选模板扫描  
4. 超过阈值 → 记录点 → 点击或作为状态证据  
5. 多模板场景用「优先序 / 互斥组」（卡牌面板 vs 技能面板 vs 主线）

---

## 7. 模式与产品行为（文档 + Settings 交叉还原）

| GameMode / 开关 | 含义 | 关键设置 |
|-----------------|------|----------|
| 独狼 | 自己点开始 | 默认 |
| 带队/车头 | 房间自动开始；房间名/密码 | `RoomName` `RoomPassword` `NewRoomEveryTimes` |
| 赌木 | 主线 + 第一宝物；OSK；找到赌木暂停 | `AutoGamblingTime`；UI `woodMode` |
| 邪修秘境 | 独立，其它功能无效 | 文档描述 |
| 自动秘境 | 结束后进秘境 | `AutoSecretRealm` |
| 自动 F4 / 关主线 | 5-5 清怪关主线 | `AutoCloseMainLine` `CloseMainLineTime` |
| 自动清理 | 每 N 局分解/合成 | `AutoCleanInterval` |
| 奥数增伤卡 | 优先特定四卡 | `DamageIncreaseCard` |
| 自动卡/武器 | 羁绊与升级 | `AutoCard` `AutoWeapon` |
| 自动声望 | 声望线 Boss/关卡 | `AutoReputation` `Reputation*` |
| 龙珠 | 数量 6/7 | `DragonBallCount`；`LongzhuJob`；`FindLongzhuWhereMultiGame` |

时间类参数：

- `QueryTimeOut` — 等待/查询超时（帮助称「等待时间」，建议偏长）  
- `DevelopTime` — 发育时间（0=快刷，1500≈24 分钟）  
- `ArchiveBossTime` — 存档挑战计时  
- `GameTimeOut` / `BoosLiveTime` / `KillBossNum` / `CycleNum` / `TreasureNum`  

关卡：

- `Stage1` / `Stage2`  
- 声望线：`ReputationStage1/2` + `ReputationCJBBoss` / `ReputationSGZXBoss`  
- Boss 选择：`CJBBoss` / `SGZXBoss`  

---

## 8. Settings 完整属性表（反射还原）

```
Stage1, Stage2
RoomPassword, RoomName, NewRoomEveryTimes
QueryTimeOut, GameTimeOut, GameMode
DragonBallCount, FindLongzhuWhereMultiGame
AutoSecretRealm, AutoCloseMainLine, CloseMainLineTime
AutoCleanInterval, AutoCard, AutoWeapon
DamageIncreaseCard, DevelopPriority, DevelopTime
AutoReputation, ContinueReputation, CleanReputationDate
ReputationLevel1..6, ReputationStage1/2
ReputationCJBBoss, ReputationSGZXBoss
CJBBoss, SGZXBoss
Skills: List, Cards: List
BoosLiveTime, KillBossNum, CycleNum
ArchiveBossTime, TreasureNum, AutoGamblingTime
LicenseTxt, BatFile, CertEnable
```

默认 `.config` 片段：`Stage1=3, Stage2=2, QueryTimeOut=60, DragonBallCount=7, Skills=jq,pg, GameMode=0, GameTimeOut=15`。

---

## 9. 授权模块（仅架构说明，重建可拆）

现存链路：

```
DeviceId → machineCode UI
    → Standard.Licensing 证书 (LicenseTxt / 选文件)
    → CertClient.StartAsync/StopAsync + SignalR Hub 事件
    → OnLicenseAccepted / OnLicenseRejected / OnRequestLocalCertificate
    → NetworkTimeHelper 防本地改时
```

**源码丢失重建时的建议：**

- **短期上手**：你若仍持有有效证书，直接跑现有 `GameScript.exe` 最快。  
- **长期自研**：自动化核心与授权解耦；新工程可不接入旧 Hub/旧公钥，避免被旧服务绑定。  
- 本文档 **不包含** 绕过/伪造证书的任何步骤。

---

## 10. 依赖清单（AssemblyRef）

| 包 | 用途 |
|----|------|
| OpenCvSharp / Extensions | 找图 |
| Lan.UIAutomation* / Interop | 窗口自动化 |
| H.InputSimulator | 输入 |
| Gma.System.MouseKeyHook | 全局热键 |
| HandyControl + CommunityToolkit.Mvvm | UI/MVVM |
| Standard.Licensing + BouncyCastle | 证书 |
| DeviceId* | 机器码 |
| SignalR Client 10 | 在线 Hub |
| NetworkTime | NTP |
| NLog | 日志 |
| Newtonsoft.Json | JSON 设置 |
| Costura | 单文件依赖 |

`_recovery/costura/` 下已抽出嵌入 DLL（含 OpenCvSharp、Lan.*、Standard.Licensing 等）便于对照。

---

## 11. 推荐重建里程碑（快速可用优先）

### M0 — 当天能点（MVP）

1. 找窗口 + 截图  
2. 模板匹配 `startGameBtn` / `continueGame` / `fail`  
3. 循环：开始 → 等待 → 失败重试/继续  
4. 配置：匹配阈值、点击偏移、急停热键  
5. 使用现有 `Images/`（你确认自有的模板库）

### M1 — 主线可刷

1. `SelectStage`（Stage1/Stage2 区域）  
2. 卡牌/技能面板关闭：`CloseCardPanel` / `CloseSkillPanel`  
3. `ChangeMainLineStatus`、超时 `QueryTimeOut`/`DevelopTime`  
4. `QuitGame` 与局数统计  

### M2 — 模式分叉

1. 独狼 / 带队建房  
2. 龙珠 `LongzhuJob`  
3. 传家宝/Boss 图库点选  
4. 自动秘境 / 声望开关  

### M3 — 工程化

1. JSON Settings 对齐上表  
2. 日志 NLog  
3. 防息屏  
4. （可选）自有授权，与旧体系分离  

---

## 12. 本目录恢复产物

| 文件 | 内容 |
|------|------|
| `ARCHITECTURE.md` | 本文 |
| `metadata.json` / `metadata_report.md` | 类型/方法/依赖元数据 |
| `type_dump.txt` / `readable_methods.txt` | 反射成员 |
| `images_inventory.txt` | 模板清单 |
| `costura/*` | 抽出的依赖 DLL |
| `all_types.txt` | 全类型名 |

---

## 13. 风险与缺口

1. **方法体混淆**：具体点击坐标、阈值、分支条件需跑测或进一步反编译 IL 精修。  
2. **UserStrings 流异常**：部分字符串被保护，中文文案以 `Help.html` / `使用前阅读.html` 为准。  
3. **SignalR 服务端**：旧证书 Hub 地址/协议需有服务器侧资料才能完整恢复在线授权。  
4. **最快可用**：重建 MVP 往往比 100% 还原混淆方法体更快；模板库 + 状态机是价值中心。
