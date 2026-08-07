# 原版 1.3.9 GameScript.exe 英雄模式/声望（Reputation）挑战 IL 拆解分析报告

## 摘要 (Summary)

本报告通过使用 dnfile 与 dncil 对 GameScript.exe（1.3.9 版）主程序集以及 Costura 提取的依赖 DLL 进行反汇编与静态 IL 深度分析，完整还原了原版程序中“英雄模式/声望挑战”的自动化控制流程、界面坐标计算逻辑、阵营与难度配置驱动关系。

---

## 一、 英雄模式入口方式 (Hero Mode Entry Protocol)

### 1.1 结论 (Key Conclusion)
* **原版挂机脚本在自动化主流程中【不通过图像识别/坐标点击】去主动点击选关页底部的「英雄模式」按钮。**
* 英雄模式与声望挑战的开启**完全由配置项 AutoReputation（自动声望/英雄挑战开关）驱动**。
* 当 AutoReputation = true 时，程序内部在选关判断/任务路由逻辑中自动切入声望挑战链路（Method 123 I5GKCMSRxI 与 Method 144 Run）。
* 在选关主循环 Method 89 (RVA 0x6754) 中，存在唯一的英雄模式检测代码（IL_067b ~ IL_06a1）：
  - IL_067b: call get_Settings()
  - IL_0680: callvirt get_AutoReputation()
  - IL_0685: brfalse IL_06fe (跳过英雄模式检测)
  - IL_068a: ldarg.0 (UIAutomation/Mouse)
  - IL_0690: ldc.i4 315
  - IL_0695: ldc.i4 100
  - IL_0697: ldc.i4 415
  - IL_069c: ldc.i4 135
  - IL_06a1: call Rect (创建 ROI 区域 Rect(315, 100, 100, 35))
  该区域 ROI Rect(315, 100, 100, 35) 位于选关界面上方标头区域，用于通过 OpenCV 模板匹配校验当前是否已成功进入英雄/声望挑战界面，若匹配成功 (0.76 阈值)，则确认处于英雄模式面板。

---

## 二、 声望阵营选择坐标与计算逻辑 (Faction Selection Coordinates & Logic)

### 2.1 阵营坐标映射 (Faction Screen Coordinates)
声望界面中一共有 6 个阵营，在 1600x900 游戏视口（UI 坐标系）下分为两排，每排 3 个阵营：
1. **黑锋骑士团** (Index 1 / ReputationLevel1)：(385, 355) ~ (390, 360)
2. **银色北伐军** (Index 2 / ReputationLevel2)：(595, 355) ~ (600, 360)
3. **肯瑞托** (Index 3 / ReputationLevel3)：(800, 355) ~ (805, 360)
4. **探险者协会** (Index 4 / ReputationLevel4)：(1010, 355) ~ (1015, 360)
5. **元素领主** (Index 5 / ReputationLevel5)：(385, 685) ~ (390, 690)
6. **守护巨龙** (Index 6 / ReputationLevel6)：(595, 685) ~ (600, 690)

### 2.2 阵营选择计算与点击逻辑 (IL Code in Method 144)
在 Method 144 (RVA 0x9850) 中，程序会依次检查 Settings 中的 6 个阵营等级配置（ReputationLevel1 ~ ReputationLevel6）：
* 若某个阵营的设定期望等级为 10 (最高级/满级标志)，程序直接点击该阵营对应的固定坐标。
* 例如 **黑锋骑士团** (ReputationLevel1 == 10)：
  - IL_00fe: callvirt get_ReputationLevel1()
  - IL_0103: ldc.i4.s 10
  - IL_0105: bne.un IL_015d
  - IL_010a: ldfld MouseEngine
  - IL_0110: ldc.i4 385 (x1)
  - IL_0115: ldc.i4 355 (y1)
  - IL_011a: ldc.i4 390 (x2)
  - IL_011f: ldc.i4 360 (y2)
  - IL_0124: call CreateRect
  - IL_012c: call MouseClick (点击黑锋骑士团)
* 若期望等级小于 10，则循环点击阵营微调按钮：
  * 排 1 阵营（Index 1-4）左侧/减按钮 X 坐标偏移：X_base = 360 (黑锋 360, 银色 570, 肯瑞托 775, 探险者 985)，Y = 355。
  * 排 2 阵营（Index 5-6）左侧/减按钮 X 坐标偏移：X_base = 360 (元素 360, 守护 570)，Y = 685。

---

## 三、 难度选择机制 (1-10 级) (Difficulty Selection Mechanism)

### 3.1 点击加/减按钮与坐标计算 (IL Logic in Method 123)
难度选择并非滚动条，而是**基于公式计算的加/减按钮点击** (在 Method 123 I5GKCMSRxI, RVA 0x8f04)。

基准 ROI 矩形区域 (IL_0076 ~ IL_0087):
* Base Rect: (X=715, Y=140, Width=245, Height=120)

难度等级计算与循环次数公式 (IL_00eb ~ IL_0122):
* **计算公式**：
  Target_Y = Base_Y + (ReputationStage - 1) * Step_Y + (ReputationStage - 1) * 10
  * Base_Y = 140
  * Step_Y = Height = 120
  * 间距 offset = 10
  * 即每跨越一个难度阶段，Y 坐标增加 120 + 10 = 130 像素。
* **IL 对应指令摘录**：
  - IL_0102: ldc.i4.1
  - IL_0103: sub           // (ReputationStage - 1)
  - IL_0104: ldflda Rect
  - IL_0109: call Height   // * Height (120)
  - IL_010f: mul
  - IL_0110: add
  - IL_0111: ldloc.0
  - IL_0112: ldfld Stage
  - IL_0117: ldc.i4.1
  - IL_0118: sub
  - IL_0119: ldc.i4.s 10   // * 10
  - IL_011b: mul
  - IL_011c: add           // 最终计算得出阵营难度按钮点击坐标

---

## 四、 「开启挑战」按钮定位与点击 (Start Challenge Button Location)

### 4.1 坐标与点击参数 (Button Coordinates)
在声望选择/配置完成后，程序自动点击右下角「开启挑战」按钮：
* **ROI 坐标矩形**：X1 = 600, Y1 = 885, X2 = 685, Y2 = 905
* **点击中心**：约 (642, 895)
* **执行方式**：连续双击/确认点击两次，间隔 200ms。

### 4.2 IL 证据 (Method 144, IL_05bb ~ IL_05fe)
- IL_05bb: ldc.i4 600   // X1
- IL_05c0: ldc.i4 885   // Y1
- IL_05c5: ldc.i4 685   // X2
- IL_05ca: ldc.i4 905   // Y2
- IL_05cf: call CreateRect(600, 885, 685, 905)
- IL_05d7: call ClickWrapper (点击开启挑战)
- IL_05fe: call ClickWrapper (再次点击确认开启挑战)

---

## 五、 配置驱动流程与数据流 (Config Driven Process Flow)

程序的英雄/声望挑战自动化由 Settings (TypeDef 78) 中的以下核心字段完全驱动：

| 配置项 | 类型 | 默认值 | 作用与驱动逻辑 |
| :--- | :--- | :--- | :--- |
| AutoReputation | bool | false | 总开关。为 true 时进入英雄/声望挂机主逻辑 |
| ReputationStage1 | int | 1 | 阶段 1 挑战难度选择 (1-10) |
| ReputationStage2 | int | 2 | 阶段 2 挑战难度选择 (1-10) |
| ReputationCJBBoss | string |  | 纯阳宫/超级霸 Boss 特殊挑战关卡名称 |
| ReputationSGZXBoss | string |  | 水晶宫/三国天下 Boss 特殊挑战关卡名称 |
| ContinueReputation | bool | true | 完成刷声望后是否继续进行下一轮声望挑战 |

### 底层 API 包装关系 (Mouse & Automation Assembly)
程序中的点击均通过嵌入的 Lan.UIAutomationCore.dll 中的 Mouse 类方法包装调用：
* 调用的底层方法：Mouse.Click(Point point, int delay)
* Win32 底层 API 转换：调用 SetCursorPos(x, y) 并发送 mouse_event(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_LEFTUP)。

---

## 六、 证据段 (Evidence Section - Verbatim IL & RVA)

1. **主选关流程入口 (Method 89 Run, RVA 0x6754, Offset 0x4954)**:
   * IL_067b: call token(0x060001AF) -> get_Settings()
   * IL_0680: callvirt token(0x060001D2) -> get_AutoReputation()
   * IL_0690: ldc.i4 315, IL_0695: ldc.i4.s 100, IL_0697: ldc.i4 415, IL_069c: ldc.i4 135 -> Rect(315, 100, 415, 135)

2. **难度计算公式 (Method 123 I5GKCMSRxI, RVA 0x8f04, Offset 0x7104)**:
   * IL_00d0: callvirt token(0x060001E2) -> get_ReputationStage1()
   * IL_00e0: callvirt token(0x060001E4) -> get_ReputationStage2()
   * IL_0102: ldc.i4.1, IL_0103: sub, IL_010f: mul, IL_0119: ldc.i4.s 10, IL_011c: add

3. **声望阵营与开启挑战坐标 (Method 144 Run, RVA 0x9850, Offset 0x7c50)**:
   * 黑锋骑士团: Rect(385, 355, 390, 360)
   * 银色北伐军: Rect(595, 355, 600, 360)
   * 肯瑞托: Rect(800, 355, 805, 360)
   * 探险者协会: Rect(1010, 355, 1015, 360)
   * 元素领主: Rect(385, 685, 390, 690)
   * 守护巨龙: Rect(595, 685, 600, 690)
   * 开启挑战按钮: Rect(600, 885, 685, 905)

4. **鼠标点击包装函数 (MethodDef token 0x06000315, RVA 0x17334)**:
   * 内部调用 Lan.UIAutomationCore.Input.Mouse::Click() 进行点按操作。
