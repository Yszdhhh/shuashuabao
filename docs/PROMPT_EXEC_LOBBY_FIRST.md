# 执行 Agent 提示词 · 优先解决「大厅/房间进不去」

> **用法**：把本文从「# 角色与任务」到文末整段复制给执行 Agent。  
> **工作区**：`G:\刷刷宝\GameScript-Local\`
> **优先级**：先打通 **L0 大厅/房间 → 进入游戏**；局内选卡/龙珠/面板美化一律后置。

---

# 角色与任务

你是执行型工程 Agent。在 **GameScript-Local** 内实现并验证：

**P0（本迭代唯一目标）**：用户已打开游戏、已在房间（或大厅），脚本能**稳定识别并点击「开始游戏」**，使官方/本地日志能从  
`等待进入游戏UI` 推进到 **`开始主线！`**（或本地等价阶段 `MAIN_LINE`）。

**不做（本迭代）**：带队自动建房完整流、证书、声望完整分支、前端大改版、救 QMacro。

---

# 问题定性（必须先认同再写代码）

## 分层

| 层 | 内容 | 现状 |
|----|------|------|
| **L0 大厅/房间** | 建房、密码、等人、点「开始游戏」 | **缺口**：模板少、无独立状态；用户卡在这里 |
| **L1 局内** | 选关后选卡/技能/龙珠/Boss | 已有大量 `assets/Images` 与日志；不是本迭代主攻 |

## 用户现象

- 自己建好房间，脚本在跑，**一直不点开始**  
- 日志长时间：`等待进入游戏UI` → 超时 `未找到关卡/主线UI,未找到位置`  
- 官方独狼文档写的是「**自己点房间开始**」；带队才强调房间自动开始/建房参数  
- 本地 `mediator` 只有粗 `start` 模板（`startGameBtn/jihuo/continueGame`），匹配常失败  

## 成功判据（验收）

1. 游戏窗口约 **1600×900** 窗口化，人在**房间界面**（可见开始按钮）  
2. 本地 dry-run 或实点：日志出现明确一行  
   `[L0] lobby start click` / `房间内点击开始`（坐标或模板名）  
3. 实点后游戏进入加载/选关；随后出现 **`开始主线`** 或本地 `phase → MAIN_LINE`  
4. 文档更新：`docs/LOBBY_ROOM_GAP.md` 增加「已实现/如何截模板」小节  
5. 回归：`python -m py_compile` 相关模块无错；`main.py dry-run --steps 5` 不崩  

---

# 强制阅读顺序（打开文件，不要凭聊天猜）

## 1. 问题与日志（P0）

1. `docs/LOBBY_ROOM_GAP.md` — L0/L1、独狼语义、模板缺口  
2. `docs/LOGIC_ROOM_STAGE_REP_SKILL.md` — 等待进入 UI 卡点  
3. `docs/agent_shared_logs/README.md` — 共享日志入口  
4. `docs/agent_shared_logs/INDEX_FOR_AGENTS.md`  
5. `docs/agent_shared_logs/exports/LOG_LOBBY_AND_ENTRY_EXTRACT.md` — 进局相关日志摘录  
6. `docs/agent_shared_logs/official_raw/` 下 `*log*.log` 与 `*Capture*` / `*QuitGame*`  
7. `docs/SUCCESS_FLOW.md` — 成功进主线长什么样  

刷新日志（若用户刚跑过官方）：

```powershell
cd "G:\刷刷宝\GameScript-Local"
powershell -File tools\export_agent_logs.ps1
```

## 2. 实现相关代码（P0）

8. `src/gamescript/mediator.py` — 重点 `PREPARE` / `WAIT_UI` / `tick`  
9. `config/scenes.json` — `"start"` 节点仅有 startGameBtn/continueGame/jihuo  
10. `src/gamescript/vision/matcher.py` — matchTemplate / imdecode（中文路径）  
11. `src/gamescript/vision/capture.py` — 按 window_title 截窗  
12. `src/gamescript/settings.py` — `window_title_contains`, `query_timeout`, `game_mode`  
13. `config/default_settings.json`  
14. `assets/Images/startGameBtn.png`, `jihuo.png`, `continueGame.png`  

## 3. 配置与模式语义

15. `%AppData%\Roaming\GameScript\Settings\Settings.json`（只读同步）  
16. `docs/使用前阅读.plain.txt` — 独狼/带队原文  

## 4. 技术方向与参考项目（学习用，不必整仓迁移）

17. 本文「参考项目」一节  
18. （可选）网易 Airtest 文档：图像点击与设备抽象思路  

**不要**优先读 UI 大改文档（`HANDOFF_FRONTEND_*`）除非 L0 已验收。

---

# 实现规格：L0「房间点开始」

## 状态机改动（建议）

在 `mediator.py` 增加相位（名称可微调，但日志必须可 grep）：

```
BOOT → LOBBY_ROOM → WAIT_UI → MAIN_LINE → …（后续不动）
```

| 相位 | 行为 |
|------|------|
| `LOBBY_ROOM` | 截游戏窗；匹配 **lobby 开始按钮** 模板列表；命中则点击；日志 `[L0] click start score=…` |
| 若匹配失败 | 日志 `[L0] miss lobby start，请确认在房间界面或更新模板`；不要误点桌面 |
| 连续 N 次 miss 或超时 | 可回退尝试旧 `scenes.start`；仍失败则保持 LOBBY_ROOM 或软失败，**禁止**假报「开始主线」 |
| 点到后 | 进入 `WAIT_UI`，等待 stage/card 等 L1 标志 |

`game_mode==0`（独狼）本迭代**必须**支持房间内点击开始。  
`CreateRoom`/密码输入：**本迭代不做**（文档标明 TODO）。

## 模板目录约定

```
assets/Images/lobby/
  room_start.png          # 用户/你截取的当前客户端「开始游戏」按钮
  room_start_alt.png      # 可选第二皮肤/分辨率
```

`config/scenes.json` 增加例如：

```json
"lobby_start": {
  "templates": ["lobby/room_start", "lobby/room_start_alt", "startGameBtn", "jihuo"],
  "method": "EntryF1",
  "action": "click"
}
```

若仓库尚无 `lobby/*.png`：

1. 从 `docs/agent_shared_logs` / `runtime_sample` 里**房间截图**裁按钮区域导出；或  
2. 运行说明要求用户提供；或  
3. 用现有 Capture 里含「开始游戏」的窗口图裁切生成初版模板  

**禁止**用全桌面匹配当默认（必须 `window_title_contains`，默认可试 `英雄三国`）。

## 识别参数

- 阈值：可对 lobby 单独略降（如 0.75–0.85），写在 settings 或 scenes 注释  
- 点击：模板中心 + `click_delay_ms`  
- 每次 tick 只截一次窗（保持现有性能习惯）

## 日志规范（给排障）

```
[L0] phase=LOBBY_ROOM
[L0] match room_start score=0.xx @ (x,y)
[L0] click start
[L0] → WAIT_UI
[L1] 开始主线 / phase=MAIN_LINE
```

---

# 下一步技术方向（验收 L0 后的路线图，本迭代只写文档可）

1. **L0 完成**：房间开始 → 稳定进 `开始主线`  
2. **L0 增强（带队后置）**：CreateRoom、密码、每局新房（需更多模板与输入）  
3. **L1 巩固**：选卡/技能短码、锚点 Boss、龙珠阶段（已有日志与模板）  
4. **工程形态**：Python + OpenCV 状态机（保持）；可借鉴 Airtest API 习惯，不整仓替换  
5. **面板**：Web/现有 ui 只展示 L0 阶段警告；不阻塞 L0 代码  
6. **弃用**：QMacro 2014 宏 exe（兼容性差、不可扩展）  

---

# 参考项目（学习改造，勿整抄侵权业务）

| 项目 | 链接 | 学什么 |
|------|------|--------|
| Airtest | https://github.com/AirtestProject/Airtest | 图像定位 UI、跨端自动化 API、脚本结构 |
| Poco | https://github.com/AirtestProject/Poco | 有控件树时的定位；本游戏可能用不上，知悉即可 |
| OpenCV 游戏检测教程 | https://github.com/learncodebygaming/opencv_tutorials | 截屏+template match+点击教学骨架 |
| 本仓库 | GameScript-Local | 配置、scenes、mediator、Images、共享日志 |

技术选型结论（写入你的 PR/说明）：

- **主路线**：Python + mss/截窗 + OpenCV matchTemplate + 显式状态机  
- **不选**：QMacro/按键精灵作底座  
- **可选参考**：Airtest 的封装与多尺度匹配思路  

---

# 实现检查清单

- [ ] `assets/Images/lobby/` 至少 1 张可用开始按钮模板  
- [ ] `scenes.json` 含 `lobby_start`  
- [ ] `mediator.py` 含 `LOBBY_ROOM`，独狼默认进入该相位（或从 BOOT 检测到房间图后进入）  
- [ ] 日志带 `[L0]` 前缀  
- [ ] `window_title_contains` 生效，避免全屏乱点  
- [ ] dry-run 能打印将要点击的坐标  
- [ ] 更新 `docs/LOBBY_ROOM_GAP.md`「已实现」  
- [ ] 更新 `docs/agent_shared_logs/INDEX_FOR_AGENTS.md` 一句进度  

---

# 禁止

- 破解/伪造 GameScript 证书  
- 本迭代实现完整带队建房却无模板  
- 删除 `assets/Images`  
- 未读共享日志就改 L1 选卡逻辑「假装修好进房」  
- 把 QMacro 当依赖  

---

# 验收口述（给用户）

完成时用中文说明：

1. 改了哪些文件  
2. 用户如何截「开始游戏」按钮（若需更新模板）  
3. 如何 dry-run / 实点验证  
4. 若仍卡住，应看日志哪一行  

---

# 用户环境备忘

- 游戏标题关键字样例：`英雄三国`  
- 建议分辨率：窗口化 **1600×900**，缩放 100%  
- 官方配置：`%AppData%\Roaming\GameScript\Settings\Settings.json`  
- 官方日志：`%LocalAppData%\GameScript\{日期}\log.log`  
- 共享导出：`docs/agent_shared_logs/`  

**现在开始：先读 LOBBY_ROOM_GAP 与 agent_shared_logs，再改 mediator + scenes + lobby 模板。**
