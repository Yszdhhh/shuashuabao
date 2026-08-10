# GameScript-Local · 本地刷图助手

从 `1.3.3.3` 发布包恢复的**本地可维护工程**：自动化核心骨架 + 官方模板库 + **高保真 Web 控制面板**。

> **产品定位**：免证书、无网络依赖的本地挂机工具控制台；默认安全模式仍是独狼，显式打开 L0 自动建房后才会操作大厅建房。

---

## 🚀 快速启动控制面板

```powershell
cd "C:\Users\10639\Desktop\🎮 影音游戏\GameScript-Local"
pip install -r requirements.txt

# 方式 1：双击或在命令行运行启动脚本
.\启动面板.bat

# 方式 2：手动启动后端 API
python api_server.py
# 浏览器访问: http://localhost:17880
```

---

## 🎨 功能特性 (信息架构)

- **顶栏状态与免证书提示**：实时高亮显示运行状态（空闲 / 运行中 / 出错）、阶段文案以及 `Shift+F12` 急停提示。
- **常规运行配置 (P0)**：
  - 目标关卡 range (`stage1` — `stage2`)；可用 `stage_targets` 精确指定如 `1-10`
  - L0 自动建房开关、房间名/密码、每局重新建房选项
  - 主线/地图 Boss (`sgzx_boss`) 与 传家宝 Boss (`cjb_boss`) **动态扫描下拉**
  - 龙珠数 (1-10)、等待 UI 超时 (秒)、发育时间 (秒，0=快刷)
  - 自动卡组 / 自动武器 / 奥数增伤 / 发育优先 / 自动秘境 快捷开关
- **声望配置 (P1 折叠)**：声望总开关、关卡起止、声望 Boss 下拉。
- **技能配置网格 (Skills)**：
  - 动态扫描 `assets/Images/skills/*.png`
  - 图标与缩略图预览网格，一键支持「全选」、「清空」、「重置为官方标准 4 技能 (`asj, asjg, assx, jq`)」
- **环境与调试**：
  - 游戏窗口标题锁定 (`window_title_contains`)
  - **Dry-run 调试模式**（醒目黄色警告，只匹配显示坐标不真实点击鼠标）
  - OpenCV 相似度阈值滑动条 (0.50 – 0.99)
- **高级运维 (P2 折叠)**：点击延迟、循环休眠、内存清理间隔、Boss 存活上限、存档超时等。
- **实时控制台日志**：支持增量推流、关键字高亮、过滤搜索、自动滚屏与日志一键复制。

### L0 建房与选关

Mediator 按显式状态链运行：`PLATFORM_MAP → CREATE_ROOM → ROOM_WAITING → ROOM_STARTING → STAGE_SELECT → STAGE_STARTING`。
全局蓝色按钮兜底已移除；没有确认页面语义或两个输入框时会停住并记录日志，不会点击“快速加入”或“取消”。

---

## 🔌 后端 API 接口

`api_server.py` FastAPI 服务提供以下 RESTful 接口：

| HTTP 方法 | 路径 | 功能说明 |
|-----------|------|----------|
| `GET` | `/api/health` | 后端健康检查与官方配置检测 |
| `GET` | `/api/settings` | 读取 `config/default_settings.json` |
| `PUT` | `/api/settings` | 保存更新配置 |
| `POST` | `/api/settings/sync-official` | 从 `%AppData%\Roaming\GameScript\Settings\Settings.json` 同步官方配置 |
| `GET` | `/api/options/skills` | 动态扫描技能短码与图片路径 |
| `GET` | `/api/options/bosses` | 动态扫描主线/传家宝 Boss |
| `POST` | `/api/run/start` | 启动 Mediator 自动化刷图任务 |
| `POST` | `/api/run/stop` | 停止当前运行的任务 |
| `GET` | `/api/run/status` | 获取当前运行阶段、局数与最近错误 |
| `GET` | `/api/run/logs?since=N` | 增量日志流 |

---

## 🛠️ 前端开发 (Vite + React + TS + Tailwind)

前端源码位于 `ui/` 目录：

```powershell
cd ui
npm install
npm run dev     # 启动开发服务器 (http://localhost:3000)
npm run build   # 编译静态产物至 ui/dist，由 FastAPI 自动托管
```

---

## 📁 工程目录结构

```
GameScript-Local/
├── 启动面板.bat           # 一键启动 Web 面板
├── 启动控制器.bat         # 选单启动 (Web / Tk 原型)
├── api_server.py           # FastAPI 后端服务 (端口 17880)
├── main.py                 # CLI 入口
├── controller.py           # 旧 Tkinter 原型
├── requirements.txt        # Python 依赖
├── config/
│   ├── default_settings.json  # 本地配置 (snake_case)
│   └── scenes.json            # 场景/模板表
├── assets/Images/          # 模板图集 (skills/boss/chuanjiaobao/cards)
├── ui/                     # Vite+React+TS+Tailwind 前端源码
│   └── dist/               # 静态托管打包产物
├── docs/                   # 架构与交接材料
│   └── agent_shared_logs/  # ★ 外部 Agent 读这里的日志/截图
│       ├── README.md
│       ├── INDEX_FOR_AGENTS.md
│       ├── official_raw/   # 官方 log + Capture/Quit 截图
│       └── exports/        # 大厅进局摘录等
└── src/gamescript/         # 自动化 Mediator 与基础模块
```

### 外部 Agent 共享日志

其它 Agent 请固定读：

`docs/agent_shared_logs/README.md`

刷新本机官方日志到该目录：

```powershell
powershell -File tools\export_agent_logs.ps1
```

大厅不点开始 / 卡在进局：见 `docs/LOBBY_ROOM_GAP.md` + `docs/agent_shared_logs/exports/LOG_LOBBY_AND_ENTRY_EXTRACT.md`

---

## ⚠️ 注意事项

1. **游戏设置**：请将游戏客户端设置为 **窗口化 1600 × 900**，系统显示缩放设置为 **100%**。
2. **安全与免证书**：本工程为本地自理版，不含证书联网及房间带队代码。

### 运行时场景判定（Solo L0 → L1）

每次 tick 先判定上下文，再执行动作，优先级为：

```text
已在局内（卡牌/技能面板） → MAIN_LINE
选关页 → 选择 stage_targets 或 Stage1—Stage2 → 点击棕色开始
房间等待页 → 点击房间开始游戏
建房弹窗 → 安全识别两个输入框 → 点击创建
大厅地图页 → 只在配置侧识别创建房间 → 等待弹窗
未知页面 → 只等待并记录，不猜测点击
```

KK 平台允许大厅主窗口与房间窗口同名；运行时会枚举所有可见、未最小化的候选窗口，按页面锚点选择真正含有“创建/开始/选关”内容的窗口。截图阶段不抢前台；真实点击前只把已验证的目标 HWND 临时置前，避免后台坐标落到其他程序。

> `dry_run=true` 是观察模式：只找图、记录 incident 和打印坐标，不会点击，也不会因未知/未支持页面自行终止；首次真机验证请先用少量 `max_steps`，确认日志出现 `context=ROOM_WAITING` / `ROOM_STARTING` / `STAGE_SELECT` 后再关闭 Dry-run。被其他窗口完全遮挡或最小化的游戏画面不能由 MSS 可靠读取，脚本会等待而不是盲点。`dry_run=false` 仍对识别不确定保持 Fail-Closed。
