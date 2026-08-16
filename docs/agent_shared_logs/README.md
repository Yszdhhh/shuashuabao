# Agent 共享日志与证据目录（给外部 Agent 读）

> **固定路径（请其它 Agent 优先打开这里）**  
> `GameScript-Local/docs/agent_shared_logs/`  
> 绝对路径示例：  
> `G:\刷刷宝\GameScript-Local\docs\agent_shared_logs\`

本目录存放：官方脚本运行日志摘录、诊断截图、大厅/进局问题结论索引。  
**刷新方式**：在项目根运行  
`powershell -File tools/export_agent_logs.ps1`  
（见同目录说明；脚本在 `tools/`）。

---

## 目录结构

```
agent_shared_logs/
├── README.md                          ← 本索引（Agent 从这读起）
├── INDEX_FOR_AGENTS.md                ← 读什么、先看啥、当前卡点
├── official_raw/                      ← 从本机 AppData 拷出的原始日志/截图
│   ├── log_YYYYMMDD.log               ← 全量日志
│   └── YYYYMMDD_*.png                 ← CaptureScreen / CaptureWindow / QuitGame
└── exports/                           ← 整理后的摘录与样例
    ├── LOG_LOBBY_AND_ENTRY_EXTRACT.md ← 大厅/进局相关行（去掉刷屏「卡都找完了」）
    ├── log_success_run_1438.txt       ← 成功进主线片段
    ├── Settings.redacted.json         ← 配置样例（证书已脱敏）
    └── *.png                          ← 关键界面截图副本
```

官方日志原位（实时、可能比本目录新）：

- `%LocalAppData%\GameScript\{yyyyMMdd}\log.log`
- `%AppData%\Roaming\GameScript\Settings\Settings.json`

---

## 当前卡点（2026-08-04 结论）

1. **大厅/房间层（L0）未完整实现**：建房、密码、房间内点「开始游戏」素材与本地状态机不足。  
2. **局内层（L1）** 才是模板大头：开始主线、选卡、技能、龙珠…  
3. 用户站在**自己建好的房间**里等脚本点开始 → 日志常停在 **`等待进入游戏UI`**，超时 **`未找到关卡/主线UI`**。  
4. 官方帮助：**独狼模式需自己点房间开始**；房间名/密码/**仅带队有效**。  
5. 详细说明：`../LOBBY_ROOM_GAP.md`、`../LOGIC_ROOM_STAGE_REP_SKILL.md`  
6. 给 Agent 的提示词：`../PROMPT_LOBBY_AND_AGENT.txt`

---

## 建议阅读顺序（外部 Agent）

1. 本文件 + `INDEX_FOR_AGENTS.md`  
2. `exports/LOG_LOBBY_AND_ENTRY_EXTRACT.md`  
3. `../LOBBY_ROOM_GAP.md`  
4. `official_raw/log_*.log`（需要全文时）  
5. `exports/CaptureWindow_*.png` / `QuitGame_*.png`  
6. `../../src/gamescript/mediator.py` + `../../config/scenes.json`

---

## 日志关键词速查

| 关键词 | 含义 |
|--------|------|
| 等待进入游戏UI | 卡在 L0→L1，等选关/主线 |
| 未找到关卡/主线UI | 超时仍在大厅/房间或分辨率不对 |
| 开始主线 | 已进入局内 L1 |
| 卡都找完了 | 局内选卡循环 |
| 已经准备游戏了 | 准备阶段结束，≠已点房间开始成功加载 |
| CreateRoom（代码痕迹） | 官方有建房逻辑；本地模板不全 |

---

## 更新约定

- 每次用户完整跑一轮官方脚本后，运行 `tools/export_agent_logs.ps1` 刷新本目录。  
- 不要只依赖聊天记录；以本目录文件为准。
