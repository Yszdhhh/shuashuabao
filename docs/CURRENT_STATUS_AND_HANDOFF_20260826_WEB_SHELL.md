# OD12 生产化 Web 壳迁移交付报告 (2026-08-26)

## 1. 交付概览
- **工作树路径**: `G:\刷刷宝\Worktrees\GameScript-WebShell-20260826`
- **分支名**: `feat/web-shell-align-20260826`
- **金标来源**: `C:\Users\10639\Desktop\刷刷宝源文件\dashboard-design-sandbox-12.html`（SHA-256 `87853c961a229ccc70ae2032ac5bce61e38a9e1f25ecba962d68fd533f2ae6f1`）
- **核心原则**: 原样生产化（零重写、零新组件框架、零远程资源依赖、严格白名单 Facade 接入）。

## 2. 交付物清单
1. **前端工程 (`ui-v2/`)**:
   - `ui-v2/dist/index.html`（115.74 kB，由 OD12 原样构建，移除沙盒外壳、`.studio`、`.notes` 与远程字体）
   - `ui-v2/src/bridge/qtBridge.ts`（QWebChannel 桥接，10s 超时防挂死）与 `mockBridge.ts`
   - `ui-v2/public/assets/`（完全本地化 UI 资源，支持离线）
   - `npm test`: 12/12 passed；`npm run check`: clean；`npm run build`: 387ms。
2. **后端 Facade (`src/shuabao/shell/dashboard_facade.py`)**:
   - 继承自 `QObject`，仅暴露 7 个 `@Slot` 白名单（全 JSON 进出）。
   - 配置改动经 `Settings._from_dict` 清洗，`_shell` 字段完整往返保留。
   - 启停操作唯一接入 `RunnerService.start / stop`，禁止任何 Mediator/api_server 旁路。
3. **桌面宿主 (`src/shuabao/shell/web_config_shell.py` & `desktop_app.py`)**:
   - 托管 `QWebEngineView` 与 `QWebChannel`，实施严格的安全拦截（阻止外部导航/弹窗/未受控下载）。
   - 捕获 `closeEvent` 联动安全停止链；
   - `desktop_app.py` 增加 `SHUABAO_SHELL=web` 受控分支，默认保持原生 `MainWindow`，完全不破坏当前快捷方式。
4. **打包规范更新 (`ShuaBao.spec` & `requirements-desktop.txt`)**:
   - `datas` 包含 `ui-v2/dist -> web/dist`；
   - `hiddenimports` 包含 `PySide6.QtWebEngineWidgets`, `PySide6.QtWebEngineCore`, `PySide6.QtWebChannel`；
   - `requirements-desktop.txt` 升级为完整 `PySide6>=6.7`。
   - `build_release.ps1` 先执行 `npm ci && npm run build`，再调用 PyInstaller，避免陈旧前端产物进入包。

## 3. 验收证据
1. **端到端真机冒烟 (`tools/smoke_web_shell_e2e.py`)**:
   - 独立临时 AppData 测试，18/18 项检查全通过；
   - `cycle_num=7/dry_run=True` 成功落盘并在重启后完整读回；
   - `normal_farm` 模式在学习模式下成功启动、接收日志与状态流转，随后安全停止恢复 IDLE 并释放 `live.lock`；
2. **多缩放比渲染截图 (`docs/screenshots/`)**:
   - `web_shell_100pct.png` (920x720)
   - `web_shell_125pct.png` (1150x900)
   - `web_shell_150pct.png` (1380x1080)
3. **测试套件**:
   - Python Scoped 测试: 62 passed；
   - Web Vitest + TSC: 12 passed / clean；
   - 发布门禁 `release_gate.py`: 保持与会话前基线一致，未引入新回归。

## 4. 正式版整合收尾（2026-08-26）

- Web 启动器默认使用隔离的 `%LOCALAPPDATA%\ShuaBaoWeb`，不触碰用户正式
  `%LOCALAPPDATA%\ShuaBao`。需要与原生看板共用 Settings 时，启动前显式设置
  `SHUABAO_APP_DATA=%LOCALAPPDATA%\ShuaBao`；此模式与原生实例共享单实例锁和
  `live.lock`，因此互斥是预期保护，不得同时运行。启动仍为 UAC 管理员模式。

  ```powershell
  # 默认：直接双击 Web 预览快捷方式，使用 %LOCALAPPDATA%\ShuaBaoWeb
  # 明确共用正式数据（仅在原生看板完全退出后）：
  $env:SHUABAO_APP_DATA = "$env:LOCALAPPDATA\ShuaBao"
  cscript //nologo .\tools\launch_web_shell.vbs
  ```
- QWebChannel 收敛为规格中的 7 个 Slot / 3 个信号；`ModeDTO` 与 TypeScript 契约严格同形，
  超过 4 个技能或 24 字符配对码整包拒绝且不落盘。
- OD12 的关卡、房间名/密码、带车/跟车/蹭车路由已接真实 Settings/ModeSpec；蹭车启动资格
  不再由沙盒文案硬编码，统一服从后端 `startable`。
- Web 宿主补齐原生运行职责：同一 RunnerService 驱动 OverlayHud、托盘停止、F12/Shift+F12，
  运行时最小化、结束后恢复；修复 QtWebEngine profile 析构顺序导致的 Python 3.13 退出崩溃。
- `smoke_web_shell_e2e.py` 增加非黑屏像素门禁；临时 AppData dry-run 18/18 通过。
  [旧的 `web_shell_*.png`] 是离屏功能截图，只能证明页面渲染。另已使用 Windows
  桌面外部抓屏生成 `web_shell_desktop_100pct.png`（920×720）和
  `web_shell_desktop_125pct.png`（1150×900），二者完整且无黑屏；
  `web_shell_desktop_150pct.png`（1380×1080）显示本机 1080px 高工作区被任务栏覆盖
  底部，不能判定通过。三图仅覆盖浅色蹭车页，farm 三栏、向导、声望内模态、抽屉和深色
  主题仍缺真机截图，不冒充全矩阵验收。
- `build_release.ps1 -SkipGate -NoDeploy` 已构建出 `dist/ShuaBao/ShuaBao.exe`，并确认
  包内有 `web/dist/index.html`、`QtWebEngineProcess.exe`、ICU 和 locale `.pak` 资源。
  自动化会话无法完成带 `uac_admin` 成品的 UAC 授权，故“断网成品冷启动”尚无可接受的
  运行证据；这不是通过项。前端依赖锁定安装、TSC、Vitest 和 Vite 构建均通过。
- 本轮 scoped：前端 check/test/build 全绿（12 tests）；Facade 33 tests、WebConfigShell 19 tests 全绿。
  全仓 `release_gate.py` 仍为 0/4：冻结回放 `giveup_panel_not_fail`、scene 计数
  `ok=132` 与基线漂移、以及 L1 羁绊/宝物契约 8 failures；本壳任务未修改 L1/感知或门禁基线。
