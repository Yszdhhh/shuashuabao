# OD12 生产化 Web 壳迁移交付报告 (2026-08-26)

## 1. 交付概览
- **工作树路径**: `G:\刷刷宝\Worktrees\GameScript-WebShell-20260826`
- **分支名**: `feat/web-shell-foundation-20260826`
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
