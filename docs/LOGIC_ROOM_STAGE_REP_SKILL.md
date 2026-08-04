# 房间进游戏卡住 · 关卡/声望/技能 逻辑核查（2026-08-04）

## 1. 从房间进游戏：卡在哪？

### 1.1 官方日志证据（2026-08-03 晚间）

**成功路径样例（16:20）：**
```
验证环境成功，准备开始游戏
等待所有人退出游戏状态！
开始游戏或开始准备游戏
已经准备游戏了
等待进入游戏UI          ← 约 16:20:59
开始主线！              ← 16:21:56（约 57 秒后通过）
卡都找完了！…
自动主线失败！,等下轮继续
游戏被中断了！
```

**失败路径样例（16:25，你说「在房间里进入」）：**
```
验证环境成功，准备开始游戏
等待进入游戏UI          ← 直接跳到等 UI，少了「等退出/开始准备/已准备」
…（空等约 120 秒 = QueryTimeOut）
ERROR 未找到关卡/主线UI,未找到位置
```

### 1.2 卡点结论

| 卡住日志 | 含义 | 常见原因 |
|----------|------|----------|
| **等待进入游戏UI** | 脚本认为已准备好，在找 **选关页/主线 UI** | 人还在 **房间大厅**（只有「开始游戏」蓝按钮），脚本要点/识别的是 **关卡列表 1-3…** 不是房间按钮 |
| **未找到关卡/主线UI,未找到位置** | `QueryTimeOut`（默认 120s）内没匹配到关卡/主线控件 | ①仍在房间 ②分辨率不是 1600×900 ③模板过期 ④窗口被挡 |
| 成功时约 1 分钟后「开始主线」 | 已进入对局/选关识别成功 | 环境对齐 |

**房间 vs 选关（关键）：**

```
[房间界面]  房间号、成员列表、「开始游戏」「邀请」「退出」
     ↓  点击开始并加载成功
[选关/大厅关卡]  地图列表、1-3…1-14、「扫荡/开始游戏/英雄/考古」
     ↓  脚本日志「开始主线」
[局内]  选卡、技能、龙珠、Boss…
```

官方脚本在「等待进入游戏UI」阶段找的是 **后者（关卡/主线）**，不是房间里的「开始游戏」文案本身（模板 `startGameBtn` 与游戏内按钮还经常对不上）。

你「站在房间里等脚本送进去」时，若脚本没点上房间开始、或加载很慢、或分辨率不对 → **就卡在「等待进入游戏UI」直到超时**。

### 1.3 本地 Mediator 的对应弱点

文件：`src/gamescript/mediator.py`

- `PREPARE`：点 `start` 场景（startGameBtn/continueGame/jihuo）→ 进 `WAIT_UI`
- `WAIT_UI`：点 `stage` 场景 → 才算「开始主线」
- **没有**单独的「房间态」与「大厅选关态」区分
- 全屏误匹配时会乱点（曾匹配桌面 UI）

→ 房间进不去：**优先官方 exe + 1600×900 + 人选到选关页再挂**；本地要修好需补「房间开始」专用模板与状态。

### 1.4 其它晚间错误

```
HubException: 连接被拒绝：无效的时间。
```
官方 SignalR 证书/服务器校验 **本机时间**；与进房找图无关，但会导致在线功能异常。

---

## 2. 技能为什么不是中文？

### 2.1 数据事实

官方 `%AppData%\GameScript\Settings\Settings.json`：

```json
"Skills": ["asj", "asjg", "assx", "jq"]
```

模板目录 `assets/Images/skills/` **只有**：

```
asj.png, asjg.png, assx.png, jq.png, pg.png, ...
```

**没有任何中文文件名，Settings 里也没有 CnName 字段被持久化。**

反射里虽有 `Skill.CnName` 属性（`GameScript.Models.Skill`），但：

- 中文名应在 **exe 内嵌/资源** 或运行时表，**未写入 Settings.json**
- 本地同步只读 JSON → **只能带到短码**

### 2.2 结论

| 问题 | 答案 |
|------|------|
| 同步丢中文了？ | **否**，官方存盘本身就是短码 |
| 本地 UI 能显示中文吗？ | 需自建 `skill_labels` 映射表（或 OCR/反编译补表） |
| 找图用什么？ | **必须用短码文件名**，与中文显示无关 |

建议映射表文件（待补中文）：`config/skill_labels.json`

```json
{
  "asj": "待命名",
  "asjg": "待命名",
  "assx": "待命名",
  "jq": "待命名",
  "pg": "待命名"
}
```

（完整中文需对照游戏内技能图标或用户标注。）

---

## 3. 关卡逻辑（Stage1 / Stage2）

### 3.1 官方 UI 语义（截图 + Settings）

```
目标关卡  [Stage1]  —  [Stage2]   [地图/Boss下拉 SGZXBoss]  [传家宝 CJBBoss]
例：        1       —    10        08巨形缝合怪              01暴掠龙
```

| 字段 | 含义（核查结论） |
|------|------------------|
| **Stage1** | 目标关卡范围的 **起点**（不是「第几章」单独绝对编号的全部含义，与 UI 左框一致） |
| **Stage2** | 目标关卡范围的 **终点**（右框；曾误以为必须是 1-15 单关号） |
| **SGZXBoss** | 主线/地图侧 Boss 选择，值 = `Images/boss/{名}.png` 的 stem |
| **CJBBoss** | 传家宝 Boss，值 = `Images/chuanjiaobao/{名}.png` 的 stem |

### 3.2 运行时

- 进入对局后日志会出现 **锚点BOSS名称**（如 `07大法师阿鲁高`），由当局进度解析，**不一定等于**设置里的 SGZXBoss 字符串。
- 设置里的 Boss 更偏 **进本/挑战选择偏好**；锚点是局内识别结果。

### 3.3 错误用法

- 把 Stage2 设成 15，但当前图只到 1-14 → 可能选关失败。
- 分辨率 1936×1066 时「未找到关卡/主线 UI」高发。

---

## 4. 声望逻辑（AutoReputation）

### 4.1 字段

| 字段 | 作用 |
|------|------|
| AutoReputation | 总开关；true 时走声望相关目标 |
| ReputationStage1 / ReputationStage2 | **声望线**目标关卡范围（与常规 Stage1/2 平行） |
| ReputationCJBBoss / ReputationSGZXBoss | 声望线 Boss（平行于 CJB/SGZX） |
| ReputationLevel1..6 | 声望档位相关（具体阈值未完全反编译） |
| ContinueReputation | 是否继续声望 |
| CleanReputationDate | 清理日期标记 |

### 4.2 与常规刷图关系

```
AutoReputation = false  → 只用 Stage1/2 + CJB/SGZX 常规刷
AutoReputation = true   → 官方还会用 Reputation* 套配置
                         （何时切声望：依赖官方内部判断「可获得声望」等，日志未逐步展开）
```

帮助原文大意：开启后自动去打声望；若可获得声望为 0 则按常规跑；**赌木模式不触发自动声望**。

### 4.3 本地实现缺口

`mediator.py` **几乎未实现声望分支**，只读了 settings 字段。  
UI 上声望开关目前更多是「同步展示 + 存盘」，**不会像官方一样完整切声望线**。

---

## 5. 逻辑梳理图（给后续 Agent）

```
[用户在房间]
    │
    ▼
环境检测 OK
    │
    ├─ GameMode=0 独狼：脚本应点击房间/大厅「开始」类按钮
    │
    ▼
等待进入游戏UI  ←←← 卡点高发区（人须到选关或对局，或脚本成功点开始）
    │ 超时 QueryTimeOut
    ▼
开始主线
    │
    ├─ 选卡循环（Skills 短码优先匹配 skills/*.png）
    ├─ 技能；失败 F1
    ├─ 提前挑战 → 跳过发育
    ├─ 锚点 Boss（局内名）
    ├─ 龙珠 DragonBallCount
    ├─ AutoSecretRealm → 大秘境
    └─ AutoReputation → （官方）声望目标 Reputation*
    │
    ▼
QuitGame → 下一局
```

---

## 6. 关键文件索引

| 文件 | 内容 |
|------|------|
| `%AppData%\GameScript\Settings\Settings.json` | 官方真配置 |
| `%LocalAppData%\GameScript\{日期}\log.log` | 卡点日志 |
| `src/gamescript/settings.py` | 字段映射 |
| `src/gamescript/mediator.py` | 本地阶段机（房间态弱） |
| `config/scenes.json` | start/stage/skill 模板 |
| `assets/Images/skills/*.png` | 仅短码 |
| `docs/SUCCESS_FLOW.md` | 成功流水 |
| `docs/runtime_sample/CaptureWindow_*.png` | 选关/局内画面 |
