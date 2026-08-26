"""WebConfigShell —— QWebEngine 宿主（设计规格 §8）。

薄壳职责：
- frameless 固定 1000×780 宿主窗口，加载 ui-v2/dist/index.html（零网络）
- QWebChannel 仅注册 DashboardFacade 一个对象（§6.1 唯一注册对象）
- 严格本地限制：非 file/qrc 导航与子资源请求一律拦截；弹新窗口、下载一律拒绝；
  生产禁开发者工具
- renderProcessTerminated：原生错误页 + 重载按钮；RunnerService/HUD/急停不受影响
- closeEvent 走原生安全停止链（runner.stop() + worker 收尾），与 MainWindow 同语义

环境缺 QtWebEngine 时显式抛 ModuleNotFoundError，绝不静默回退原生（§8/§9）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtWidgets import QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

try:  # 显式依赖门禁：缺 WebEngine 直接报错退出，不静默回退。
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
        QWebEngineUrlRequestInterceptor,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError as exc:
    raise ModuleNotFoundError(
        "SHUABAO_SHELL=web 需要 PySide6 完整版（含 QtWebEngine/QtWebChannel）。"
        "请安装 requirements-desktop.txt，或去掉 SHUABAO_SHELL 使用默认原生壳。"
    ) from exc

from shuabao.shell.dashboard_facade import DashboardFacade
from shuabao.shell.runner_service import RunnerService

APP_TITLE = "刷刷宝"

#: 严格本地 scheme 白名单（§8）：本地构建产物与 Qt 资源，别的一律不放行。
ALLOWED_SCHEMES = frozenset({"file", "qrc"})

_WINDOW_W, _WINDOW_H = 1000, 780

#: QWebChannel 注册名，与 ui-v2/src/bridge/qtBridge.ts FACADE_OBJECT_NAME 对齐。
FACADE_OBJECT_NAME = "facade"


def resolve_dist_index(root: Path) -> Path:
    """定位 ui-v2 构建产物：开发仓 <root>/ui-v2/dist；打包后 _MEIPASS/web/dist（§11）。"""
    root = Path(root)
    for candidate in (
        root / "ui-v2" / "dist" / "index.html",
        root / "web" / "dist" / "index.html",
    ):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"找不到 ui-v2/dist/index.html（root={root}）；请先在 ui-v2 下执行 npm run build"
    )


class LocalOnlyPage(QWebEnginePage):
    """严格本地页：只放行 file:// 与 qrc:// 导航；弹新窗口一律拒绝（§8）。"""

    def __init__(self, profile: QWebEngineProfile, parent: QObject | None = None):
        super().__init__(profile, parent)
        self.blocked_urls: list[str] = []

    def acceptNavigationRequest(self, url: QUrl, nav_type: Any, is_main_frame: bool) -> bool:  # noqa: N802
        if url.scheme() in ALLOWED_SCHEMES:
            return True
        self.blocked_urls.append(url.toString())
        return False

    def createWindow(self, kind: Any) -> None:  # noqa: N802
        # target=_blank / window.open 一律拒绝：返回 None 即不创建任何窗口。
        self.blocked_urls.append(f"<createWindow:{kind}>")
        return None


class _LocalOnlyRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """子资源层兜底：导航白名单之外的请求（https 图片、websocket 等）直接 block。"""

    def interceptRequest(self, info: Any) -> None:  # noqa: N802
        if info.requestUrl().scheme() not in ALLOWED_SCHEMES:
            info.block(True)


class WebConfigShell(QMainWindow):
    """QWebEngineView 宿主。除 DashboardFacade 外禁止注册任何 QWebChannel 对象。"""

    def __init__(
        self,
        app_data: Path,
        root: Path | None = None,
        *,
        dist_dir: Path | None = None,
        runner: Any = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.app_data = Path(app_data)
        self.root = Path(root) if root is not None else Path.cwd()
        index = Path(dist_dir) / "index.html" if dist_dir else resolve_dist_index(self.root)

        self.setWindowTitle(APP_TITLE)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(_WINDOW_W, _WINDOW_H)

        self.profile = QWebEngineProfile(self)
        settings = self.profile.settings()
        # Qt6 起开发者工具默认关闭（DeveloperExtrasEnabled 已移除）；此处收紧其余面。
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, False)
        self.profile.setUrlRequestInterceptor(_LocalOnlyRequestInterceptor(self.profile))
        self.profile.downloadRequested.connect(lambda download: download.cancel())

        self.page = LocalOnlyPage(self.profile, self)
        self.view = QWebEngineView(self)
        self.view.setPage(self.page)
        self.setCentralWidget(self.view)

        # 唯一 LIVE 入口 RunnerService + QWebChannel 唯一注册对象（§6.1/§9）。
        self.runner = runner if runner is not None else RunnerService(self.app_data, self.root)
        self.facade = DashboardFacade(
            self.app_data,
            self.runner,
            root=self.root,
            on_minimize=self.showMinimized,
            on_close=self.close,
            parent=self,
        )
        self.channel = QWebChannel(self)
        self.channel.registerObject(FACADE_OBJECT_NAME, self.facade)
        self.page.setWebChannel(self.channel)

        # 渲染进程崩溃：原生错误页 + 重载按钮（§8）；停止链在别的对象上，不受影响。
        self.page.renderProcessTerminated.connect(self._on_render_process_terminated)
        self._crash_overlay: QWidget | None = None
        self._crash_label: QLabel | None = None

        self.view.load(QUrl.fromLocalFile(str(index)))

    # ------------------------------------------------------------- 渲染崩溃（§8）

    def _on_render_process_terminated(self, status: Any, exit_code: int) -> None:
        # 按 name 匹配：PySide 每次访问枚举成员可能生成新包装对象，dict 身份匹配不可靠。
        name = str(getattr(status, "name", "") or "")
        reasons = {
            "CrashedTerminationStatus": "页面渲染进程崩溃",
            "KilledTerminationStatus": "页面渲染进程被终止",
        }
        self._show_crash_overlay(reasons.get(name, f"页面渲染进程退出（{name or status}）"))

    def _show_crash_overlay(self, message: str) -> None:
        if self._crash_overlay is None:
            overlay = QWidget(self)
            layout = QVBoxLayout(overlay)
            self._crash_label = QLabel(message, overlay)
            reload_btn = QPushButton("重新加载", overlay)
            reload_btn.clicked.connect(self._reload_after_crash)
            layout.addWidget(self._crash_label)
            layout.addWidget(reload_btn)
            self._crash_overlay = overlay
        elif self._crash_label is not None:
            self._crash_label.setText(message)
        assert self._crash_overlay is not None
        self._crash_overlay.setGeometry(self.rect())
        self._crash_overlay.show()
        self._crash_overlay.raise_()

    def _reload_after_crash(self) -> None:
        if self._crash_overlay is not None:
            self._crash_overlay.hide()
        self.view.reload()

    # ------------------------------------------------------------- 关闭安全链（§9）

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        """运行中先 runner.stop() 并等 worker 收尾；收不了则拒绝关闭（同 MainWindow）。"""
        worker = getattr(self.runner, "worker", None)
        if worker is not None and worker.isRunning():
            self.runner.stop()
            if not worker.wait(15000):
                worker.wait(60000)
            if worker.isRunning():
                event.ignore()
                return
        try:
            self.runner.release_after_finish()
        except Exception:
            pass
        event.accept()
