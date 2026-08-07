# 原版 1.3.9 GameScript.exe SelectStage（选关）IL 拆解分析报告

> 分析对象：`C:\Users\10639\Desktop\🎮 影音游戏\1.3.9\GameScript.exe`（ConfuserEx 混淆，v4.0.30319）
> 方法：dnfile + dncil 静态反汇编；对照 1.3.8（`iDRNAJlqRN` / `BGb8I3AV9q` / `t778j8is3D`，结构逐字节一致）
> 坐标基准：游戏窗口**客户区**内像素（经 BoundingRectangle 换算为屏幕坐标）；实机录屏为 1600×900 窗口坐标（含约 30px 标题栏偏移）
> 未决项标注 UNKNOWN

---

## 一、方法定位（1.3.9 混淆名 ↔ 1.3.8 原名）

| 功能 | 1.3.9 方法（RVA / MethodDef） | 1.3.8 方法（RVA / MethodDef） |
|---|---|---|
| **SelectStage（选关主流程）** | `AutoJob::I5GKCMSRxI`（0x8F04 / 0x0600007B） | `AutoJob::iDRNAJlqRN`（0x8FB4 / 0x0600007B） |
| 等待条件①（窗口追帧态） | `<>c__DisplayClass32_0::<SelectStage>b__0`（0x9730 / 0x0600008C） | 同名（0x97F0） |
| 等待条件②（点选+验证行） | `<>c__DisplayClass32_0::<SelectStage>b__1`（0x97A4 / 0x0600008D） | 同名（0x9860） |
| **滚轮包装**（移动+滚动） | `o1acMmkEXy`（0x17218 / 0x06000312） | `BGb8I3AV9q`（0x16FB4 / 0x0600030C） |
| 移动+双击辅助 | `jCaco6ynyd`（0x17274 / 0x06000313） | `t778j8is3D`（0x17010 / 0x0600030D） |
| 点击包装（单击/双击/右键） | `Mbdc2QlJES`（0x17334 / 0x06000315） | 0x0600030F |
| 模板匹配（0.76 阈值） | `SZrczsTTbx`（0x174B4 / 0x06000317） | 0x06000311 |
| 多模板匹配（0.83 阈值） | `tO6H43KmHe`（0x1763C / 0x06000319） | 0x06000313 |
| 等待助手（轮询条件） | `IIQchy4bHD`（0x16E64 / 0x06000305） | 0x06000300 |
| 字符串解密器 | `kwNHFygbLQ`（0x20268 / 0x06000377） | 0x06000371 |
| 声望/英雄模式判定 | `hQ4mLeCphy`（0x11658 / 0x0600017E） | 0x0600017A |

SelectStage 的调用者：3 个任务 Run 方法（`QiPx0DKx0Pv4lbBxNG3::Run` 0x9850、`cxaagye1pRyXgMApQyH::Run` 0xC138、`kPbIBRej82dqHwV1BGc::Run` 0xD4CC），由主选关状态机 `IKqmBr4VjVS5MD3nBfj::Run`（0x6754）分发。

---

## 二、滚轮完整参数表（2-N 关卡，Stage2 > 12 触发）

**触发条件**：`stage2 = Settings.Stage2`（声望模式时 `= Settings.ReputationStage2`）；`stage2 > 12` 才滚动（IL_01C9：`ldloc.2; ldc.i4.s 12; ble 698` → stage2 ≤ 12 直接走无滚动分支）。

| 参数 | 值 | 来源 |
|---|---|---|
| 滚动坐标（窗口相对） | **Point(1090, 390)** | SelectStage IL_01D7–01E1 等 4 处：`ldc.i4 1090; ldc.i4 390; newobj Point` |
| 屏幕坐标换算 | `(BoundingRectangle.Left + 1090, BoundingRectangle.Top + 390)` | o1acMmkEXy IL_001F–003D |
| 每次滚轮格数 | **-1**（`ldc.i4.m1`，滚轮下滚 1 格） | IL_01E6 等 |
| 每轮滚动次数 | **4 次连续调用**（4 个独立 call 块） | IL_01D1 / 01E0 / 01FB / 0216 |
| 单次移动→滚动间隔 | **Sleep(200)ms**（在 o1acMmkEXy 内部，set_Position 之后、Scroll 之前） | o1acMmkEXy IL_0047–004C |
| 底层调用 | `Mouse.Position = 新点; Thread.Sleep(200); Mouse.Scroll((double)(-1))` | o1acMmkEXy IL_0042/004C/0053 |
| 重试轮间隔 | **Sleep(500)ms**（一轮 4 次滚动+搜索后未命中再循环） | IL_0283–028D |
| 重试上限 | **无上限（无限循环）**——每轮 = 4 次滚动 + 1 次模板搜索，直到命中 `1-23` | IL_028D `br 465` 回 IL_01D1 |
| 滚动后定位方式 | **模板匹配**：在窗口截图中找模板 `1-23`（阈值 0.83），命中即认为列表已滚到目标位置；随后用相对坐标公式算目标行 | IL_0243–027E |

> 注：`Settings.NumberOfScroll`（默认 1）在 SelectStage 中**未被使用**，滚动次数硬编码为 4。1.3.8 与 1.3.9 滚动参数逐字节一致（1.3.8 用 `BGb8I3AV9q`，同样 4 次、Point(1090,390)、-1、Sleep(200)）。

### o1acMmkEXy（滚轮包装）IL 摘录（RVA 0x17218）
```
0x0018: ldarg.0; callvirt get_BoundingRectangle ; 窗口矩形
0x001f: ldloca.s local0; call Rectangle.get_Left
0x0026: ldarga.s arg1;  call Point.get_X ; add        ; Left + 1090
0x002e: ldloca.s local0; call Rectangle.get_Y
0x0035: ldarga.s arg1;  call Point.get_Y ; add        ; Top + 390
0x003d: newobj Point
0x0042: call Mouse.set_Position                        ; 移动鼠标
0x0047: ldc.i4 200; 0x004c: call Thread::Sleep          ; 200ms
0x0051: ldarg.2; conv.r8; 0x0053: call Mouse.Scroll     ; 滚 -1 格
```

---

## 三、Stage1Rec 与 Y 公式（1-N 关卡）

### 常量
- **Stage1Rec = `Rectangle(715, 140, 245, 120)`**（`newobj Rectangle`，X=715, Y=140, W=245, H=120）——IL_0076–008C（`stfld` 到闭包类字段 `Stage1Rec`）。
- **Rect1 = `Rectangle.FromLTRB(1000, 158, 1170, 197)`**（即 X=1000, Y=158, W=170, H=39）——局部变量，IL_0091–00A5。用于 stage2 目标行。

### 目标行 Y 计算公式（IL_00EB–011D，伪代码）
```csharp
// userStage1 = Settings.Stage1（声望模式时为 Settings.ReputationStage1）
Stage1Rec.Y = Stage1Rec.Y                          // 140
            + (userStage1 - 1) * Stage1Rec.Height  // (u-1)*120
            + (userStage1 - 1) * 10;               // (u-1)*10
// 展开：Y = 140 + (u-1)*120 + (u-1)*10 = 140 + (u-1)*130
```
对应 IL：`ldflda Stage1Rec; call get_Y` → `(userStage1-1) * get_Height`（120）→ `add` → `(userStage1-1)*10` → `add` → `call Rectangle.set_Y`（**直接原地改写 Stage1Rec.Y**，后续点击复用该矩形）。

### 1-N 点击动作
```csharp
// 当字典含模板 "stage{Stage1}" 时（Stage1=1..4，见第七节）：
IIQchy4bHD(b__1, 1000, 0, 0);      // 轮询等待，超时=QueryTimeOut*1000（默认200s）
//   IIQchy4bHD 语义：pred 返回 true → 睡 1000ms 重查；pred 返回 false → 成功返回 true；超时 → false
//   b__1（0x97A4）：Mbdc2QlJES(GW, Stage1Rec, 1,0,0) 单击一次
//                 → tO6H43KmHe(GW, lE0a2gLNM, [dict["stage{u}"]]) 在首行 ROI
//                   FromLTRB(1040,160,1130,200) 内找 "stage{u}" 字形（0.83），
//                   未命中（IsEmpty）返回 true → 等待继续；命中 → 返回 false → 等待成功
//   超时（一直未命中）→ CaptureWin("no_stage_1") 截图 → throw new Exception("点击关卡失败！，未找到对应关卡锚点")
// 否则（无该模板，Stage1>4）：
Mbdc2QlJES(GW, Stage1Rec, 1, 0, 0);  // 盲单击（不验证）
Thread.Sleep(1500);
```
`Mbdc2QlJES(node, rect, a2, a3, a4)` 的参数语义：a2=1 左键 / 0 右键；a3=0 单击 / 1 双击；流程为 `Center(rect) → Mouse.Position → Sleep(200) → Click/DoubleClick`。

---

## 四、2-N 关卡选择（Stage2）差异

| | Stage2 ≤ 12（不滚动） | Stage2 > 12（需滚动） |
|---|---|---|
| 前置动作 | 无 | **4× 滚轮**（Point(1090,390)，-1 格，见第二节），然后 `tO6H43KmHe(GW, c7K5qYLeT, ["1-23"])` 在**末行 ROI FromLTRB(1040,745,1130,785)** 内模板匹配（0.83）确认滚动到位（滚动后 "1-23" 位于列表第 12 行/底部）；未命中 → Sleep(500) → 再滚 4 次（无限循环） |
| 行定位公式 | `Rect1.Y = 158 + (stage2-1)*39 + (stage2-1)*14 = 158 + (stage2-1)*53`（IL_02BA–02D6） | `Rect1.Y = 158 + (stage2-12)*39 + (stage2-12)*14 = 158 + (stage2-12)*53`（IL_0292–02B0） |
| 行高语义 | 每行 39px 高 + 14px 间距 = **53px/行**，与实机录屏 53px 行距完全一致 | 同左（以滚动后列表顶行为基准，12 行一屏） |
| 点击确认 | **双击两次**：`Sleep(500)` → `jCaco6ynyd(GW, Rect1, 1, 100)`（移动+Sleep(100)+**DoubleClick**）→ `Sleep(Settings.StageSelectInterval)`（默认 0ms）→ `Mbdc2QlJES(GW, Rect1, 1, 1, 1)`（移动+Sleep(200)+**DoubleClick**）→ ret | 同左 |

> 关键差异：1-N 是**单击**章节/行（Stage1Rec 区域，130px 行距）；2-N 是**双击确认**（Rect1 区域，53px 行距），双击 = 原版的「选关+开始」动作。
> jCaco6ynyd 与 Mbdc2QlJES 的 else 分支核心 IL 一致：`Center(rect) → Mouse.set_Position → Sleep(200) → Mouse.DoubleClick(0)`（jCaco6ynyd 的 Sleep 为 arg3=100ms）。
>
> **静态 ROI（uD24QxpEPylSpVIaMY::.cctor，RVA 0x23C4，窗口客户区坐标）**：
> - `lE0a2gLNM`(0x04000011) = `FromLTRB(1040,160,1130,200)` — 列表**首行**区域，b__1 校验 "stage{u}" 用（仅有此一处引用）
> - `c7K5qYLeT`(0x04000012) = `FromLTRB(1040,745,1130,785)` — 列表**末行**区域，滚动后搜索 "1-23" 用（仅有 SelectStage 引用）
> - 底栏按钮（其他任务用）：0x04000013=`Rectangle(710,720,270,30)`（覆盖 扫荡/开始游戏 区域，配合模板 0.76 判定）、0x04000014=`Rectangle(1060,730,120,180)`（考古区域）——**SelectStage 不使用它们**

---

## 五、「开始游戏」按钮定位与点击

**结论：原版 1.3.9/1.3.8 IL 中不存在对选关页底栏「开始游戏」按钮的点击。**

证据：
1. 全模块扫描：无任何 `ldc.i4 897` / `ldc.i4 742` / `ldc.i4 750` / `ldc.i4 1025` / `ldc.i4 1136` 常量（底栏四按钮坐标在整份代码中不出现）。
2. SelectStage 以 `Mbdc2QlJES(GW, Rect1, 1, 1, 1)`（双击 Rect1 中心 ≈(1085, 176+53·k)）结束并 `ret` —— **双击关卡行即等效「选中 + 开始游戏」**，游戏端双击行为负责启动。
3. 字符串解密表中无「开始游戏/扫荡/英雄模式/考古」相关模板名（解密出的全部 752 条字符串仅含 `stage{0}`、`1-23`、`zhuizhenzhong`、`no_stage_1` 等；UIAutomation 模式串 `<ctrl role='PUSHBUTTON' name='开始游戏' />` 属于 KK 平台**房间**页，非选关页）。

**录屏坐标的定位**：底栏 扫荡(750,742) / 开始游戏(897,742) / 英雄模式(1025,742) / 考古(1136,742) 是**本地重构版**基于实机录屏（1600×900 窗口）新增的点击（`lobby/stage_begin_btn` 模板 + 坐标），原版只依赖行双击。重构版流程：①点目标编号行（对齐 Stage1Rec/Rect1 语义）→ ②`verify_stage_selection` 校验高亮 → ③点 `stage_start`(897,742) 或（AutoReputation 时）英雄模式(1025,742)→「开启挑战」Rect(600,885,685,905)。

---

## 六、实机录屏交叉验证

| 项 | 录屏/实机（1600×900 窗） | 原版 IL | 结论 |
|---|---|---|---|
| 关卡行距 | ≈53px（y=123 起，例 1-12…1-23） | Rect1 公式 39+14=**53px**/行 | ✅ 精确一致 |
| 滚动锚点模板 | 列表尾部行 `1-23` | 模板 `1-23`（Images/1-23.png，60×30）在滚动循环中 0.83 匹配 | ✅ 模板存在且实机图内可匹配到 (1047,718) |
| 章节/行区域 | — | Stage1Rec(715,140,245,120) ≈ 模板 stage.png(248×119) | ✅ 尺寸一致 |
| 数字字形 | 列表行带 `1-` 前缀 | `stage1..4.png`(42×25) 即数字字形，实机匹配于 x≈1049、行距≈54px | ✅ |
| 窗口偏移 | 录屏 y 起 123 | IL 基准 y=158（客户区） | ✅ 差 ~30px ≈ 标题栏，坐标基准不同 |
| 底栏按钮 | (750/897/1025/1136, 742) | 原版不点击（见第五节） | ✅ 原版用行双击替代 |

---

## 七、字符串解密与模板字典（J4uK9wC9x0）

- 模板字典 `AutoJob::J4uK9wC9x0` = `Dictionary<string, Bitmap>`，在 `AutoJob::.cctor`（0x8490）中遍历 `Images\*.png` 目录加载，**key = 文件名去扩展名**。
- 字符串解密器 `kwNHFygbLQ(int key)`（0x20268）：从嵌入资源 `JLCyXr4nGcdeLXckss.pXGkDQKYw53XJrJm7K`（28,690B，本分析已用反射运行时解密全部 752 条）读取，`Encoding.Unicode.GetString(blob[key+4 .. key+4+ToInt32(blob,key)])`。
- 与选关相关的解密结果：
  - 7236 = `追帧恢复失败！`（b__0 超时日志）
  - 7254 = `zhuizheng`（b__0 超时截图文件名）
  - 8254 = `zhuizhenzhong`（b__0 的窗口就位校验模板，Images/zhuizhenzhong.png 132×20，阈值 0.76，ROI FromLTRB(670,365,950,455)）
  - 7276 = `stage{0}`（配合 `string.Format("stage{0}", userStage1)` 查字典 → stage1..4 模板，仅 1-4 章有校验模板）
  - 7296 = `no_stage_1`（选关失败截图文件名）
  - 7320 = `点击关卡失败！，未找到对应关卡锚点`（b__1 超时抛出的异常消息）
  - 7358 = `1-23`（滚动后定位锚点模板）

---

## 八、Settings 相关默认值（Settings::.ctor，0x129E4）

| 字段 | 默认 | 备注 |
|---|---|---|
| Stage1 | 3 | 选关第 1 项（章节） |
| Stage2 | 2 | 选关第 2 项（关卡行） |
| QueryTimeOut | 200 | 秒；IIQchy4bHD 轮询超时 = QueryTimeOut×1000ms |
| NumberOfScroll | 1 | SelectStage 内未使用（滚动硬编码 4 次） |
| MouseOperationInterval | 150 | ms |
| StageSelectInterval | 0（未在 ctor 设置） | ms；双击之间的间隔 |
| MoveWindow | 1 | 布尔，是否移动游戏窗口 |

---

## 九、证据段（方法 RVA + 关键 IL）

### 9.1 SelectStage 主流程 `AutoJob::I5GKCMSRxI` RVA 0x8F04（1.3.8: `iDRNAJlqRN` 0x8FB4，结构一致）
```
IL_0076: ldloc.0; ldc.i4 715; ldc.i4 140; ldc.i4 245; ldc.i4.s 120; newobj Rectangle; stfld Stage1Rec
IL_0091: ldc.i4 1000; ldc.i4 158; ldc.i4 1170; ldc.i4 197; call Rectangle::FromLTRB; stloc.1   // Rect1
IL_00AB: call Settings.get_Default; callvirt get_Stage1;  stfld userStage1
IL_00BB: call Settings.get_Default; callvirt get_Stage2;  stloc.2
IL_00C6: call hQ4mLeCphy; brfalse IL_00EB
IL_00D0: ... userStage1 = Settings.ReputationStage1; stloc.2 = Settings.ReputationStage2 ...
IL_00EB: ldflda Stage1Rec; ldflda Stage1Rec; call get_Y; ldfld userStage1; ldc.i4.1; sub
         ldflda Stage1Rec; call get_Height; mul; add
         ldfld userStage1; ldc.i4.1; sub; ldc.i4.s 10; mul; add
         call Rectangle::set_Y                                  // Stage1Rec.Y = 140+(u-1)*120+(u-1)*10
IL_0122: ldsfld J4uK9wC9x0; <key7276>; call kwNHFygbLQ; ldfld userStage1; box; call String::Format
         callvirt ContainsKey; brtrue IL_0174                   // 有 "stage{u}" 模板 → 走验证
IL_0151: Mbdc2QlJES(GameWindow, Stage1Rec, 1, 0, 0); Sleep(1500); br IL_01C9   // 无模板：盲单击
IL_0174: IIQchy4bHD(<b__1>, 1000, 0, 0); brtrue IL_01C9
IL_0191: log(7296); CaptureWin; log(7320); newobj Exception; throw   // "点击关卡失败！，未找到对应关卡锚点"
IL_01C9: ldloc.2; ldc.i4.s 12; ble IL_02BA                          // stage2<=12 → 免滚动
IL_01D1..0238: o1acMmkEXy(GameWindow, Point(1090,390), -1) ×4       // 4 次滚轮
IL_023D..027E: tO6H43KmHe(GameWindow, [dict["1-23"]]); ... brfalse IL_0283  // 找 1-23
IL_0283: Sleep(500); br IL_01D1                                     // 未命中重滚（无限）
IL_0292: Rect1.Y = Y + (stage2-12)*Height + (stage2-12)*14          // 滚动后行公式（s2>12）
IL_02BA: Rect1.Y = Y + (stage2-1)*Height + (stage2-1)*14            // 免滚动行公式（s2<=12）
IL_02DB: Sleep(500)
IL_02E5: jCaco6ynyd(GameWindow, Rect1, 1, 100)                      // 移动 + 双击①
IL_02F4: Sleep(Settings.StageSelectInterval)
IL_0303: Mbdc2QlJES(GameWindow, Rect1, 1, 1, 1)                     // 移动 + 双击②
IL_0312: ret
```

### 9.2 关键辅助方法 RVA
| 方法 | RVA | 关键 IL |
|---|---|---|
| `o1acMmkEXy`（滚轮） | 0x17218 | `Mouse.set_Position; Sleep(200); Mouse.Scroll((double)arg2)` |
| `jCaco6ynyd`（移动+双击） | 0x17274 | `Center → set_Position → Sleep(arg3) → Mouse.DoubleClick(0)` |
| `Mbdc2QlJES`（点击） | 0x17334 | `arg2=1&&arg3=0 → Click(0)`；`arg2=1&&arg3=1 → DoubleClick(0)` |
| `SZrczsTTbx`（单模板 0.76） | 0x174B4 | `Capture.Rectangle → ImageSearchEngine.Search(tpl, 0.76)` |
| `tO6H43KmHe`（多模板 0.83） | 0x1763C | `TryFindTemplateBinarized(..., 0.83)`，返回 `Tuple<Point,int>` |
| `IIQchy4bHD`（轮询等待） | 0x16E64 | `loop { if (cond()) return true; Sleep(interval); }` **更正：**`loop { if (pred()==false) return true; Sleep(1000); }`，超时=QueryTimeOut×1000（CancelAfter）→ false；返回 true = 条件结束 |
| `hQ4mLeCphy`（声望判定） | 0x11658 | `AutoReputation && (GameMode==5&&ContinueReputation || CleanReputationDate.Contains(...))` |
| `kwNHFygbLQ`（解密） | 0x20268 | `BitConverter.ToInt32(blob,key) → Array.Copy → Encoding.Unicode.GetString` |

### 9.3 b__0（0x9730）与 b__1（0x97A4）
- b__0：`SZrczsTTbx(GW, FromLTRB(670,365,950,455), dict["zhuizhenzhong"], 0.76)` → 结果**非空**返回 true（"追帧中"标识仍在窗口区域）。IIQchy4bHD(b__0,...) 等到该状态消失才算成功；超时 → 日志 `追帧恢复失败！` + `CaptureWin("zhuizheng")`，随后**继续流程**（不中断）。
- b__1：`Mbdc2QlJES(GW, Stage1Rec, 1,0,0)` 单击 → `tO6H43KmHe(GW, lE0a2gLNM, [dict[string.Format("stage{0}", userStage1)]])` 在首行 ROI(1040,160,1130,200) 内找 "stage{u}" 字形；**未命中返回 true**（等待继续），命中返回 false（等待成功）。超时（一直未命中）→ 截图 `no_stage_1` + throw `点击关卡失败！，未找到对应关卡锚点`。

### 9.4 实机模板匹配（cv2，live_stage_select.png 1600×900）
- `1-23.png`(60×30) 命中 (1047, 718)（列表尾部行），score 0.983
- `stage.png`(248×119) 命中 (705, 111)，score 0.967
- `stage1.png`(42×25) 命中 x≈1049、y=126/180/234…（行距≈54px）

### 9.5 1.3.8 对照
- 1.3.8 SelectStage `iDRNAJlqRN` 0x8FB4：Stage1Rec=(715,140,245,120)、Rect1=FromLTRB(1000,158,1170,197)、滚轮 4×(1090,390,-1)、公式 (u-1)*120+(u-1)*10 与 (s2-1)*39+(s2-1)*14 —— 与 1.3.9 逐常量一致。
- 1.3.8 滚轮包装 `BGb8I3AV9q` 0x16FB4、双击辅助 `t778j8is3D` 0x17010 的 IL 与 1.3.9 同构。

---

## 十、对本地重构的落地要点（结论摘要）

1. 滚轮：窗口相对 (1090,390) ≈ 相对 (0.68, 0.43)；每次 -1 格；连续 4 次；重试轮间隔 500ms；原版无限重试 → 本地版应加次数上限（当前实现 8 次）。
2. 行定位：1-N（Stage1）用 `140 + (u-1)*130`；2-N 用 `158 + (s2-1)*53`（≤12）或 `158 + (s2-12)*53`（>12，滚动后）。行距 53px 与实机一致；基准 y 需按窗口客户区换算（实机含 ~30px 标题栏）。
3. 滚动后确认：模板 `1-23` 0.83 匹配（本地版模板资产已有 `1-23`）。
4. 原版无「开始游戏」按钮点击，靠行双击启动；本地版新增 (897,742) 点击为对实机行为的增强，需保留 `verify_stage_selection` 前置校验。
5. 验证模板 `stage{0}`（u=1..4）与 `zhuizhenzhong`（窗口就位）可复用于本地模板匹配。
