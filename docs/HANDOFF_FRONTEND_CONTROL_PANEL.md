# 前端设计 Agent 交接文档 · 本地刷图控制面板

> **给新前端/UI Agent 的完整提示词与参考库说明。**  
> 复制下方「一键提示词」整段即可开工。  
> 产品范围：**自己刷图（独狼）**；**不做带队/建房/联网证书**。

---

## 一、一键提示词（复制给新 Agent）

```markdown
# 任务：为 GameScript-Local 设计并实现「自己刷图」控制面板前端

## 0. 你是谁 / 交付什么
你是前端与交互设计 Agent。在现有 Python 后端工程上，交付：
1) 高保真控制面板 UI（优先 Web：HTML/CSS/JS 或 React/Vite 单页；或 Electron/Tauri 壳 + 本地 API）
2) 与后端配置/启动协议对接（见下文 API）
3) 设计规范：字段、组件、状态、校验、空态/运行态/错误态
4) README：如何启动面板 + 如何联调后端

不要重做找图/自动化核心（OpenCV 中介已有）。不要做证书/联网授权。不要做带队建房。

## 1. 项目背景
- 产品：魔兽题材挂机游戏「英雄三国KK」类窗口的自动刷图助手（原官方名类似「懒人系列之魔兽世界刷刷刷」）
- 官方软件：WPF exe（GameScript 1.3.3.3），有完整联网证书 UI；源码不可用
- 本仓库：GameScript-Local，从官方包恢复的本地自动化骨架 + 配置 + 模板库
- 用户要：自己设计控制面板（字段对齐官方习惯），只服务「自己刷图」

## 2. 工程路径（Windows）
根目录：
  G:\刷刷宝\GameScript-Local\

关键路径：
  config/default_settings.json     # 本地配置（snake_case）
  config/scenes.json               # 场景→模板（前端一般只读展示，不改）
  assets/Images/                   # 找图模板
    skills/*.png                   # 技能短码 asj,jq,...
    boss/*.png                     # 主线 Boss 列表（下拉选项）
    cards/*.png                    # 卡牌
    chuanjiaobao/*.png             # 传家宝 Boss
  src/gamescript/settings.py       # 配置模型 + load_official()
  src/gamescript/mediator.py       # 运行时状态机（后端）
  docs/SUCCESS_FLOW.md             # 实机成功流水
  docs/SCENES.md                   # 场景说明
  docs/RUNTIME_AFTER_AUTH.md       # 官方运行时路径
  docs/HANDOFF_FRONTEND_CONTROL_PANEL.md  # 本文档
  docs/runtime_sample/             # 真实截图参考（官方 UI 外观）
    CaptureScreen_20260803150054.png  # 官方控制面板外观（深色）
    CaptureWindow_*.png / QuitGame_*.png  # 游戏内画面

官方配置（只读同步源，用户机器上）：
  %AppData%\Roaming\GameScript\Settings\Settings.json  # PascalCase

## 3. 设计目标（IA / 信息架构）

### 3.1 一屏主面板（推荐宽度 420–480 或宽屏 960 双栏）
参考官方深色风格（见 runtime_sample 截图）：
- 顶栏：产品名 + 版本角标「本地 · 自己刷图」+ 运行状态徽章（空闲/运行中/停止中/错误）
- 区块 A「状态」：当前局数、本局阶段文案、最近错误一行
- 区块 B「常规运行配置」：目标关卡、Boss 下拉、龙珠、超时、开关组
- 区块 C「声望运行配置」：总开关 + 关卡 + Boss（可折叠）
- 区块 D「技能设置」：多选芯片/网格（短码 + 可选缩略图）
- 区块 E「环境」：窗口标题关键字、分辨率提示、Dry-run、匹配阈值
- 底栏：主按钮「开始游戏」+「停止」+「同步官方配置」+「保存」
- 日志抽屉/底部面板：滚动日志（等宽字体）

### 3.2 不要出现
- 机器码 / 选择证书 / 到期时间（可灰显「本地免证书」一句即可）
- 房间名/密码/每局新房间/带队模式（v1 隐藏或禁用并标注「后续版本」）
- 赌木模式完整流（可后续）

### 3.3 视觉
- 深色：背景 #0b1220 / 卡片 #151c2c / 主按钮蓝 #2563eb / 成功绿 / 危险红
- 字体：系统中文 UI（微软雅黑 / Segoe UI）
- 官方参考图：docs/runtime_sample/CaptureScreen_20260803150054.png
- 不要抄官方 Logo 商标做商业分发；内部工具可用「本地刷图控制台」命名

## 4. 完整配置字段表（前端必须覆盖的绑定）

### 4.1 核心刷图（P0 · 必须可编辑）

| JSON 键 | 类型 | UI 控件 | 说明 | 默认/样例 |
|---------|------|---------|------|-----------|
| stage1 | int | 数字框 | 目标关卡起 | 1 |
| stage2 | int | 数字框 | 目标关卡止（与官方「1 — 10」一致） | 10 |
| sgzx_boss | string | 下拉 | 主线/地图 Boss，选项=assets/Images/boss 文件名去.png | 08巨形缝合怪 |
| cjb_boss | string | 下拉 | 传家宝 Boss，选项=chuanjiaobao/ | 01暴掠龙 |
| dragon_ball_count | int | 1–10 | 龙珠数量 | 7 |
| query_timeout | int | 秒 | 等待进入 UI 超时 | 120 |
| develop_time | int | 秒 | 发育时间，0=快刷 | 0 |
| skills | string[] | 多选 | 技能短码，选项=skills/*.png | ["asj","asjg","assx","jq"] |
| window_title_contains | string | 文本 | 游戏窗口标题包含，锁窗用 | 英雄三国 |
| dry_run | bool | 开关 | true=只匹配不点击 | true |
| match_threshold | float | 0.5–0.99 | 找图阈值 | 0.85 |
| auto_secret_realm | bool | 开关 | 局末自动秘境 | true |
| auto_card | bool | 开关 | 自动卡组 | true |
| auto_weapon | bool | 开关 | 自动武器 | true |
| damage_increase_card | bool | 开关 | 奥数增伤优先 | true |
| develop_priority | bool | 开关 | 发育优先 | true |

### 4.2 声望（P1 · 建议有，可折叠）

| JSON 键 | 类型 | UI |
|---------|------|-----|
| auto_reputation | bool | 总开关 |
| reputation_stage1 / reputation_stage2 | int | 关卡起止 |
| reputation_cjb_boss / reputation_sgzx_boss | string | Boss 下拉 |
| continue_reputation | bool | 继续声望 |
| reputation_level1..6 | int | 可选高级，默认可藏 |

### 4.3 运维/高级（P2 · 折叠「高级」）

| JSON 键 | 说明 |
|---------|------|
| game_timeout | 单局超时相关 |
| auto_clean_interval | 每 N 局清理 |
| boss_live_time / archive_boss_time | 局内/存档计时（龙珠阶段约 180–200s） |
| kill_boss_num / cycle_num / treasure_num | 战斗参数 |
| click_delay_ms / loop_sleep_ms | 点击/循环间隔 |
| window_size | [1600,900] 提示文案，一般只读 |
| images_dir | 模板目录，高级可改 |
| auto_close_main_line / close_main_line_time | 自动关主线/F4 |
| cards | 卡组优先列表 string[]，可二期 |
| game_mode | 固定 0（自己刷图），UI 只读展示「自己刷图」 |

### 4.4 明确不做（v1）

| JSON 键 | 原因 |
|---------|------|
| room_name / room_password / new_room_every_times | 带队 |
| find_longzhu_where_multi_game | 组队龙珠 |
| auto_gambling_time | 赌木 |
| LicenseTxt / CertEnable / BatFile | 官方证书与通知 bat |

官方 PascalCase ↔ 本地 snake_case 映射已在 `src/gamescript/settings.py` 的 `_OFFICIAL_MAP`。

## 5. 运行时状态（面板要展示）

后端阶段（mediator.Phase），建议映射中文：

| Phase | 展示文案 |
|-------|----------|
| BOOT | 就绪 |
| WAIT_EXIT | 等待退出游戏状态 |
| PREPARE | 开始/准备游戏 |
| WAIT_UI | 等待进入游戏UI |
| MAIN_LINE | 主线 / 选卡中 |
| ANCHOR_BOSS | 锚点 Boss |
| LONGZHU | 查找龙珠 |
| QUIT | 退出本局 |
| NEXT | 准备下一局 |

日志事件（后端 print / 将来 WebSocket）：
- 卡都找完了 / 未找到集火，点击F1
- 提前挑战按钮 / 锚点BOSS名称 / 开始查找龙珠N
- 自动主线失败！等下轮继续（软失败）
- 游戏被中断了（硬错误，红条）

## 6. 后端对接协议（请按此实现，可先 Mock）

### 6.1 推荐架构
```
[控制面板前端]
    HTTP localhost:17880  (FastAPI/Flask 或 现成 static+API)
         │
         ├ GET  /api/health
         ├ GET  /api/settings          → 当前配置 JSON
         ├ PUT  /api/settings          → 保存 config/default_settings.json
         ├ POST /api/settings/sync-official  → Settings.load_official() 写回
         ├ GET  /api/options/skills    → skills 目录 stem 列表
         ├ GET  /api/options/bosses    → { main: [], cjb: [] }
         ├ GET  /api/options/cards     → cards stems
         ├ POST /api/run/start         → body: { dry_run?, max_steps? } 启动 Mediator 线程
         ├ POST /api/run/stop
         ├ GET  /api/run/status        → { running, phase, game_count, last_error }
         └ GET  /api/run/logs?since=   → 增量日志行
```

若暂不做 HTTP：可用
- `python controller.py` 作参考实现；或
- 前端只产出静态设计 + `settings.json` 读写约定，由用户后接 API。

**优先交付：可运行的前端 + mock API 或真实 API。**

### 6.2 配置文件格式
读写 `config/default_settings.json`，UTF-8，snake_case，示例见仓库内文件。

### 6.3 启动命令（用户侧）
```
cd GameScript-Local
python -m pip install -r requirements.txt
# 方案 A：你实现的 web UI
python -m uvicorn ...  # 或你的启动方式
# 方案 B：保留 CLI
python main.py sync-settings
python main.py dry-run --steps 30
```

## 7. 主要功能清单（验收标准）

### P0 必须
- [ ] 深色控制面板，分区清晰（状态/常规/声望/技能/环境/操作/日志）
- [ ] 所有 P0 字段可编辑并保存到 default_settings.json
- [ ] Boss/技能选项从 `assets/Images` 扫描，不硬编码死
- [ ] 「同步官方配置」可读 `%AppData%\GameScript\Settings\Settings.json`
- [ ] 「开始 / 停止」可驱动后端（或 mock 状态机动画）
- [ ] Dry-run 开关醒目
- [ ] game_mode 固定展示为「自己刷图」，不可误选带队
- [ ] 响应式：高度不足时分区可滚动，主按钮固定底栏可选
- [ ] 中文文案，无证书诱导流程

### P1 建议
- [ ] 运行状态徽章 + 阶段文案
- [ ] 日志面板自动滚动、错误行高亮
- [ ] 分辨率提示条：请将游戏设为窗口化 1600×900
- [ ] 技能多选支持「全选/清空/仅同步项」
- [ ] 保存成功 toast

### P2 可选
- [ ] 模板缩略图预览（skills/boss 小图）
- [ ] 主题切换
- [ ] 导出/导入配置 JSON
- [ ] 简易「环境检测」按钮（检测窗口标题是否存在 — 可调后端）

## 8. 交互与校验

- stage1/stage2：1–50 整数，stage1 可不强制 ≤ stage2（官方允许用户乱填，但可黄字警告）
- dragon_ball_count：1–10
- match_threshold：0.50–0.99
- skills 为空：允许，但提示「将使用默认全图技能匹配，可能较慢」
- 点击开始时 dry_run=false：二次确认「将控制鼠标点击」
- 运行中：禁用大部分编辑，或「停止后才能改」

## 9. 参考库（设计与实现）

### 9.1 本仓库必读
| 路径 | 用途 |
|------|------|
| docs/runtime_sample/CaptureScreen_20260803150054.png | **官方面板视觉参考** |
| docs/SUCCESS_FLOW.md | 运行阶段与日志 |
| docs/SCENES.md / config/scenes.json | 场景与模板 |
| config/default_settings.json | 当前真实配置样例 |
| src/gamescript/settings.py | 字段定义与官方映射 |
| src/gamescript/mediator.py | 后端阶段机（对接 start/stop） |
| assets/Images/** | 下拉与多选数据源 |
| controller.py | 旧 tk 原型（字段可参考，视觉可推翻） |

### 9.2 推荐前端技术（任选其一，写进交付说明）
- **推荐**：Vite + React + TypeScript + Tailwind；本地 FastAPI 静态托管
- 或：纯 HTML/CSS/JS 单文件 + FastAPI
- 或：保持桌面：PySide6/DearPyGui（若 Agent 更熟 Python GUI）
- 组件灵感：shadcn/ui、Headless UI（深色 dashboard）
- 图标：Lucide
- 不要引入需联网 CDN 才能打开的硬依赖（可离线打包）

### 9.3 游戏/业务参考（勿爬取侵权素材商用）
- 游戏窗口标题关键字样例：`英雄三国`
- 官方日志目录：`%LocalAppData%\GameScript\{yyyyMMdd}\log.log`
- 帮助语义：1600×900 窗口化、缩放 100%、Shift+F12 急停（官方）

## 10. 信息架构线框（文字版）

```
┌─────────────────────────────────────────┐
│ 懒人系列·本地刷图    [本地] [●空闲]     │
├─────────────────────────────────────────┤
│ 状态  局数: 0   阶段: 就绪              │
│       最近: —                           │
├─────────────────────────────────────────┤
│ 常规运行配置                            │
│  目标关卡 [1] — [10]                    │
│  Boss [下拉主线]  传家宝 [下拉]          │
│  龙珠[7] 等待UI[120] 发育[0]            │
│  [x]自动卡 [x]武器 [x]奥数 [ ]秘境 …   │
├─────────────────────────────────────────┤
│ 声望运行配置              [ ]开启       │
│  关卡 [1]—[10]  Boss…                   │
├─────────────────────────────────────────┤
│ 技能  [asj][asjg][assx][jq] …网格多选  │
├─────────────────────────────────────────┤
│ 环境  窗口标题 [英雄三国] [x]Dry-run    │
│       阈值 [0.85]  提示:1600×900        │
├─────────────────────────────────────────┤
│ [同步官方] [保存]              步数[0]  │
│ ┌─────────────────────────────────────┐ │
│ │         开  始  游  戏              │ │
│ └─────────────────────────────────────┘ │
│ [停止]                                  │
├─────────────────────────────────────────┤
│ 日志                                    │
│  > …                                    │
└─────────────────────────────────────────┘
```

## 11. 非目标 / 边界

- 不破解、不绕过官方证书；本地面板不实现 License
- 不复制官方商标商用；内部工具命名「本地刷图控制台」即可
- 不实现带队/房间
- 不重写 OpenCV 核心（调用现有 Python 模块/API）
- 自动化合规：仅用户自有游戏窗口；用户自负游戏 ToS 风险

## 12. 交付物清单

1. `ui/` 或 `web/` 源码目录  
2. 启动方式（npm run dev / python serve）  
3. 与 `config/default_settings.json` 双向绑定  
4. （可选）`api_server.py` FastAPI 最小实现接 Mediator  
5. 截图 2 张：空闲态、运行态  
6. 简短 CHANGELOG：相对旧 tk controller 的改进点  

## 13. 验收口令

用户可以说：「用官方同步的技能 asj/asjg/assx/jq，关卡 1-10，dry-run 点开始，日志出现 phase 变化」即验收通过。

---

工作目录必须是 GameScript-Local。先读 docs/runtime_sample 官方面板截图与 config/default_settings.json，再动手。
```

---

## 二、给产品/你自己的摘要

### 控制面板定位
- **不是**官方 WPF 的像素克隆（做不到直接引用）
- **是**按官方用户习惯重新设计的 **本地自己刷图控制台**
- 数据以 `Settings` 字段 + Images 列表为准

### 推荐分区
1. 状态  
2. 常规运行配置（关卡/Boss/龙珠/开关）  
3. 声望（可折叠）  
4. 技能多选  
5. 环境（窗口标题、Dry-run、阈值）  
6. 开始/停止/同步/保存  
7. 日志  

### 后端已有能力（前端 Agent 对接）
- `Settings.load_official()` / `save()`
- `Mediator.run/stop`
- `scenes.json` + `assets/Images`
- CLI：`main.py sync-settings|dry-run|run`

### 当前临时 UI
- `controller.py` + `启动控制器.bat`：原型，可被新前端完全替换

---

## 三、文件位置

| 文件 | 用途 |
|------|------|
| **本文** `docs/HANDOFF_FRONTEND_CONTROL_PANEL.md` | 完整交接 |
| 一键提示词 | 见上文第一节代码块 |
| 视觉参考 | `docs/runtime_sample/CaptureScreen_20260803150054.png` |

把第一节代码块整段复制给新的前端设计 Agent 即可。
