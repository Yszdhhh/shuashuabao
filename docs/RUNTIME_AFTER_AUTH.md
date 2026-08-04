# 授权开通后新增路径与可恢复量

扫描时间：2026-08-03（本机已跑通证书导入 + 至少一次启动）

---

## 1. 授权前后差在哪？

| | 未授权 / 只拆 exe | 授权并运行后 |
|--|------------------|--------------|
| 程序体 / Images | 有 | 相同，**无新 DLL/模板路径** |
| 混淆代码 | 仍混淆 | **不会因授权解开混淆** |
| 用户配置 | `.exe.config` 默认片段 | **`%AppData%\GameScript\Settings\Settings.json` 完整实参** |
| 运行日志 | 无 | **`%LocalAppData%\GameScript\{yyyyMMdd}\log.log`** |
| 失败截图 | 无 | **`CaptureScreen_*.png` / `Auto_Main_Line_Fail_*.png`** |
| 证书内容 | 空 | Settings 里 `LicenseTxt`（Standard.Licensing XML） |

结论：**授权打开的是「运行权 + 真实配置/日志/截图」数据面，不是源码面。**

---

## 2. 本机新增路径（重要）

```
%AppData%\Roaming\GameScript\
  Settings\Settings.json          ← 真实业务配置 + LicenseTxt

%LocalAppData%\GameScript\
  {yyyyMMdd}\
    log.log                       ← NLog 风格运行流水
    CaptureScreen_*.png           ← CaptureWin 全屏/截屏留档（本机样例 1920×1080）
    Auto_Main_Line_Fail_*.png     ← 主线失败标记图（本机样例 1×1 占位）
```

发布目录 `1.3.3.3\` 本身**没有**因授权多出可执行逻辑文件。

本仓库已导入：

- `docs/runtime_sample/log.log`
- `docs/runtime_sample/CaptureScreen_sample.png`
- `docs/runtime_sample/Settings.redacted.json`（证书正文脱敏）
- `config/default_settings.json`（由真实 Settings **映射业务字段**，不含可用证书）

---

## 3. 日志还原的真实运行流水（比闭包更准）

```
保存配置
  → 检测 OSK / 检测游戏
  → 复制机器码 / 导入证书（CertEnable）
  →「验证环境成功，准备开始游戏」
  →「等待所有人退出游戏状态！」
  →「开始游戏或开始准备游戏」
  →「已经准备游戏了」
  →「等待进入游戏UI」
  → [超时]「没找到游戏进入标识！」   ← 对应 mainIdentifier 类模板
  →「开始主线！」
  →「自动主线失败！」
  → Exception「游戏被中断了！」
       stack: 找图/节点层 → LongzhuJob? or AutoJob.Run → UI 启动器
```

可对齐本地状态名：

| 日志文案 | 本地/原方法 |
|----------|-------------|
| 验证环境成功 | Valida / 环境检测 |
| 等待所有人退出游戏状态 | 进房前门闩 |
| 开始游戏或开始准备游戏 | BeginGame / EntryF1 |
| 已经准备游戏了 | 准备完成标志 |
| 等待进入游戏UI | FindNodeWithTimeOut(进入标识) |
| 没找到游戏进入标识 | `mainIdentifier` 未命中 |
| 开始主线 / 自动主线失败 | ChangeMainLineStatus / 主线循环 |
| CaptureScreen_* | CaptureWin |

---

## 4. 真实 Settings 高价值字段（已写入 default_settings）

来自你机器上的 `Settings.json`（业务侧，非破解）：

| 字段 | 你的值 | 含义提示 |
|------|--------|----------|
| GameMode | **3** | 文档 4 模式之一（0 独狼…3 多半邪修/某模式，待 UI 对照） |
| QueryTimeOut | **120** | 等待进入 UI 约 2 分钟量级（日志 13:55:38→13:57:02） |
| Stage1/2 | 2 / 1 | 关卡 |
| CJBBoss | `10马格纳斯` | 对齐 `chuanjiaobao/10马格纳斯.png` |
| SGZXBoss | `12卡尔加` | 对齐 `boss/12卡尔加.png` |
| Reputation*Boss | 猛虎之神 / 拉格纳罗斯 | 声望线 Boss 图名 |
| DragonBallCount | 7 | |
| AutoCleanInterval | 5 | 每 5 局清理 |
| DamageIncreaseCard | true | 奥数增伤 |
| DevelopPriority | true | 发育优先 |
| DevelopTime | 0 | 快刷 |
| NewRoomEveryTimes | true | 每局新房 |
| RoomPassword | 有 | 带队相关 |
| CycleNum | 99 | |
| BoosLiveTime / ArchiveBossTime | 200 | |
| KillBossNum | 800 | |
| TreasureNum | 1 | |
| CertEnable | true | 已开证书校验 |
| Skills / Cards | [] | 你当前未勾选列表 |

Boss 命名规则已坐实：**配置字符串 = 模板文件名（无 .png）**。

---

## 5. 证书形态（仅结构，本地自研不依赖）

- 库：`Standard.Licensing` XML  
- `Type`: Standard  
- `ProductFeatures`: `name` + `machineCode`（绑机）  
- `Signature`: ECDSA/RSA 签名串  
- `Expiration`: 证书内过期时间  

**授权不会**把公钥校验改成明文源码。  
本地 `GameScript-Local` **不加载**该 License；试用自动化靠自有循环 + 模板。

---

## 6. 能恢复到本地自用的比例（务实）

| 模块 | 可恢复度 | 授权后增益 |
|------|----------|------------|
| 模板库 Images | ~100% 资产 | 无新图 |
| Settings 字段与实参 | **~95%** | **巨大**（真实 JSON） |
| 主流程状态文案/顺序 | **~80%** | **巨大**（log） |
| 场景→模板映射 | ~70% | 小（Boss 名规则确认） |
| 找图阈值 / ROI | ~20% | 截图可辅助标定 |
| CreateRoom 坐标/OCR | ~10% | 无 |
| 混淆方法体逐行 | ~15% | **无**（仍混淆） |
| 在线 SignalR 协议细节 | ~5% | 日志未暴露 Hub URL |
| 可用「免证书克隆商业壳」 | 0%（不做） | — |

**本地自用自动化 MVP：约 60–75% 够用**（配置+模板+日志状态机+找图点击）。  
**100% 行为复刻：仍缺 ROI/阈值/部分模式分支。**

---

## 7. 建议用法

1. **正经挂机**：继续用已授权的官方 `GameScript.exe`（你已开通）。  
2. **本地工程试用**：`GameScript-Local` 已同步你的业务参数；`dry_run` 标定 `mainIdentifier` / `startGameBtn`。  
3. **继续喂数据**：每失败一次，把 `%LocalAppData%\GameScript\日期\` 下新 log + CaptureScreen 拷进 `docs/runtime_sample/`，状态表可继续加厚。  

---

## 8. 本次你这次运行的结论（业务）

- 环境检测已通过，能进「准备游戏 → 等待进入 UI」。  
- 失败点：**没找到游戏进入标识**（`mainIdentifier` 或同类）→ 主线直接失败。  
- 截屏为 **1920×1080 全屏**，不是 1600×900 客户区——若游戏窗更小，官方也可能先全屏找，或当时未锁窗。  
- 本地重建应优先：**锁游戏窗 + 校验 mainIdentifier 模板是否与当前客户端一致**。
