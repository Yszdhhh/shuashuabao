"""WebConfigShell —— QWebEngine 宿主（设计规格 §8）。

薄壳职责：
- frameless 宿主窗口与 OD12 产品窗同尺寸（1080×820），加载 ui-v2/dist/index.html（零网络）
- QWebChannel 仅注册 DashboardFacade 一个对象（§6.1 唯一注册对象）
- 严格本地限制：非 file/qrc 导航与子资源请求一律拦截；弹新窗口、下载一律拒绝；
  生产禁开发者工具
- renderProcessTerminated：原生错误页 + 重载按钮；RunnerService/HUD/急停不受影响
- closeEvent 走原生安全停止链（runner.stop() + worker 收尾），与 MainWindow 同语义

环境缺 QtWebEngine 时显式抛 ModuleNotFoundError，绝不静默回退原生（§8/§9）。
"""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

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
from shuabao.shell.bridge_contract import BRIDGE_SCHEMA_VERSION
from shuabao.shell.mode_catalog import get_spec
from shuabao.shell.overlay_hud import OverlayHud
from shuabao.shell.runner_service import RunnerService

APP_TITLE = "刷刷宝"

#: 严格本地 scheme 白名单（§8）：本地构建产物与 Qt 资源，别的一律不放行。
ALLOWED_SCHEMES = frozenset({"file", "qrc"})

_DASHBOARD_SIZE = (1080, 820)
# 向导按内容分配宿主高度：单人只有一个选项，组队包含三种关系。
# 宽度保持与 Web 沙盒一致；chooser 作为旧调用方的组队兼容别名。
_CHOOSER_SOLO_SIZE = (560, 300)
_CHOOSER_TEAM_SIZE = (560, 560)
_CHOOSER_SIZE = _CHOOSER_TEAM_SIZE
_TITLEBAR_DRAG_WIDTH, _TITLEBAR_DRAG_HEIGHT = 690, 40

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
            _validate_dist_manifest(candidate, root)
            return candidate.resolve()
    raise FileNotFoundError(
        f"找不到 ui-v2/dist/index.html（root={root}）；请先在 ui-v2 下执行 npm run build"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_sha(root: Path) -> str | None:
    candidates = [Path(root)]
    if getattr(sys, "executable", None):
        candidates.append(Path(sys.executable).resolve().parent)
    if Path(root).parent not in candidates:
        candidates.append(Path(root).parent)
    for candidate in candidates:
        identity = candidate / "build_identity.json"
        try:
            payload = json.loads(identity.read_text(encoding="utf-8"))
            value = str(payload.get("source_sha") or "").strip()
            if value:
                return value
        except (OSError, ValueError, AttributeError):
            pass
    if (root / ".git").exists():
        proc = _run_git(root, "rev-parse", "HEAD")
        if proc is not None and proc.returncode == 0:
            value = proc.stdout.strip()
            return value or None
    return None


def _run_git(root: Path, *git_args: str) -> subprocess.CompletedProcess[str] | None:
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 3,
        "check": False,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        return subprocess.run(["git", "-C", str(root), *git_args], **kwargs)
    except (OSError, subprocess.SubprocessError):
        return None


def _worktree_dirty(root: Path) -> bool:
    """Return whether a source checkout has uncommitted files."""
    if not (Path(root) / ".git").exists():
        return False
    proc = _run_git(root, "status", "--porcelain", "--untracked-files=all")
    if proc is None:
        return True
    return bool(proc.returncode == 0 and proc.stdout.strip())


def _validate_dist_manifest(index: Path, root: Path) -> None:
    """Reject a stale/partial UI bundle when a build manifest is present.

    Hand-built test fixtures and source checkouts without a manifest remain
    usable; release builds always emit one.  This makes source/dist drift an
    explicit startup failure instead of silently running yesterday's UI.
    """
    manifest_path = index.parent / "build_manifest.json"
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"UI 构建清单无法读取: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise RuntimeError(f"UI 构建清单 schema 不受支持: {manifest_path}")
    expected_index_hash = str(manifest.get("index_sha256") or "").lower()
    if expected_index_hash and expected_index_hash != _sha256(index).lower():
        raise RuntimeError("UI 构建清单与 index.html 不一致，请重新 npm run build")
    try:
        bridge_schema = int(manifest.get("bridge_schema_version", -1))
    except (TypeError, ValueError):
        bridge_schema = -1
    if bridge_schema != BRIDGE_SCHEMA_VERSION:
        raise RuntimeError(
            "UI 构建产物与 Python bridge schema 不一致："
            f"manifest={manifest.get('bridge_schema_version')} current={BRIDGE_SCHEMA_VERSION}"
        )
    if manifest.get("source_tree_clean") is True and _worktree_dirty(root):
        raise RuntimeError("UI 构建清单来自干净源码，但当前 checkout 有未提交修改；请重新构建")
    expected_source = _source_sha(root)
    manifest_source = str(manifest.get("source_sha") or "").strip()
    if expected_source and manifest_source and expected_source != manifest_source:
        raise RuntimeError(
            "UI 构建产物与当前源码提交不一致："
            f"manifest={manifest_source[:12]} current={expected_source[:12]}"
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


class _TitlebarDragRegion(QWidget):
    """覆盖 WebEngine 标题栏的非交互区，保证鼠标按下由原生 Qt 接收。"""

    def __init__(self, shell: "WebConfigShell"):
        super().__init__(shell)
        self._shell = shell
        self.setGeometry(0, 0, _TITLEBAR_DRAG_WIDTH, _TITLEBAR_DRAG_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setStyleSheet("background: transparent;")

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._shell._begin_window_drag()
            event.accept()
            return
        super().mousePressEvent(event)


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
        if dist_dir:
            index = Path(dist_dir) / "index.html"
            if not index.is_file():
                raise FileNotFoundError(f"找不到指定 Web 构建产物：{index}")
            _validate_dist_manifest(index, self.root)
        else:
            index = resolve_dist_index(self.root)

        self.setWindowTitle(APP_TITLE)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(*_DASHBOARD_SIZE)

        # profile 必须晚于 page/view 销毁；若同挂在窗口下，Qt 子对象析构顺序会让
        # profile 先释放，Python 3.13 + QtWebEngine 退出时可触发访问冲突。
        self.profile = QWebEngineProfile()
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
        self.view.setContentsMargins(0, 0, 0, 0)
        self.view.setStyleSheet("QWebEngineView { border: 0; }")
        self.view.setPage(self.page)
        self.setCentralWidget(self.view)
        self._titlebar_drag_region = _TitlebarDragRegion(self)
        self._titlebar_drag_region.raise_()

        # 唯一 LIVE 入口 RunnerService + QWebChannel 唯一注册对象（§6.1/§9）。
        self.runner = runner if runner is not None else RunnerService(self.app_data, self.root)
        self.facade = DashboardFacade(
            self.app_data,
            self.runner,
            root=self.root,
            on_minimize=self.showMinimized,
            on_close=self.close,
            on_layout=self._set_window_layout,
            parent=self,
        )
        self.channel = QWebChannel(self)
        self.channel.registerObject(FACADE_OBJECT_NAME, self.facade)
        self.page.setWebChannel(self.channel)

        # 原生运行职责与 Web 配置页共用同一 RunnerService：HUD / 托盘 / F12
        # 都回到 facade.stop_run()，不产生第二条停止旁路。
        self.overlay_hud = OverlayHud()
        self.overlay_hud.stop_requested.connect(self._request_stop)
        self._runtime_active = False
        self.facade.run_status_changed.connect(self._on_runtime_status)
        for seq in ("F12", "Shift+F12"):
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self._request_stop)
        self._setup_tray()

        # 渲染进程崩溃：原生错误页 + 重载按钮（§8）；停止链在别的对象上，不受影响。
        self.page.renderProcessTerminated.connect(self._on_render_process_terminated)
        self._crash_overlay: QWidget | None = None
        self._crash_label: QLabel | None = None

        self.view.load(QUrl.fromLocalFile(str(index)))

    def _set_window_layout(self, layout: str) -> None:
        """让看板与运行方式向导按内容使用相称的独立窗口。"""
        if layout == "chooser-solo":
            width, height = _CHOOSER_SOLO_SIZE
        elif layout in {"chooser", "chooser-team"}:
            width, height = _CHOOSER_TEAM_SIZE
        else:
            width, height = _DASHBOARD_SIZE
        if (self.width(), self.height()) != (width, height):
            self.setFixedSize(width, height)
        # 只覆盖标题文字区；紧凑页必须保留右侧最小化/关闭按钮的点击权。
        self._titlebar_drag_region.setGeometry(
            0, 0, max(0, width - 230), _TITLEBAR_DRAG_HEIGHT
        )

    def _begin_window_drag(self) -> None:
        """在 WebEngine 收到鼠标按下的同一时刻切换到 Windows 标题栏拖动。"""
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.ReleaseCapture()
            ctypes.windll.user32.SendMessageW(int(self.winId()), 0xA1, 2, 0)
            return
        handle = self.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    # ------------------------------------------------------------- 原生运行职责（§9）

    def _setup_tray(self) -> None:
        menu = QMenu(self)
        show_action = QAction("打开控制中心", self)
        show_action.triggered.connect(self.showNormal)
        stop_action = QAction("停止运行", self)
        stop_action.triggered.connect(self._request_stop)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(show_action)
        menu.addAction(stop_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray = QSystemTrayIcon(self)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(APP_TITLE)
        icon = self.windowIcon()
        if icon.isNull():
            for path in (self.root / "assets" / "branding" / "app_logo.ico",
                         self.root / "assets" / "branding" / "app_logo.png"):
                if path.is_file():
                    icon = QIcon(str(path))
                    break
        if not icon.isNull():
            self.tray.setIcon(icon)
        if QSystemTrayIcon.isSystemTrayAvailable() and not self.tray.icon().isNull():
            self.tray.show()

    def _request_stop(self) -> None:
        self.facade.stop_run()

    def _on_runtime_status(self, payload: str) -> None:
        try:
            run = json.loads(payload)
        except (TypeError, ValueError):
            return
        active = str(run.get("state") or "") in {"STARTING", "RUNNING", "STOPPING"}
        # The overlay describes the run that is actually executing.  User
        # edits made while the worker is alive must not rewrite its target,
        # mode strategy, or other launch facts; those come from the immutable
        # RunnerService startup snapshot until the next run.
        started_getter = getattr(self.runner, "started_settings", None)
        try:
            started_settings = started_getter() if callable(started_getter) else None
        except Exception:
            started_settings = None
        settings = started_settings or getattr(self.runner, "_started_settings", None) or self.facade._settings
        mode_id = str(run.get("mode_id") or settings.mode_id or "normal_farm")
        if mode_id == "lobby_hitch":
            target = f"大厅找房({settings.hitch_stage_prefix or '4,3'})"
        elif mode_id == "follow_team":
            target = f"跟随跟车({settings.follow_pair_code or '自动'})"
        else:
            target = (settings.stage_targets or [f"{settings.stage1}-{settings.stage2}"])[0]
        hud_modes = {
            "normal_farm": "单人模式",
            "follow_team": "组队跟车模式",
            "lobby_hitch": "组队蹭车模式",
        }
        mode = hud_modes.get(mode_id)
        if not mode:
            try:
                mode = get_spec(mode_id).label
            except Exception:
                mode = mode_id
        strategy = "自动秘境" if settings.auto_secret_realm else (
            "声望挑战" if settings.auto_reputation else "自动推进"
        )
        worker = getattr(self.runner, "worker", None)
        mediator = getattr(worker, "mediator", None)
        if mediator is not None:
            self.overlay_hud.anchor_to_target(getattr(mediator, "_last_frame", None))
        self.overlay_hud.update_status(
            active,
            str(run.get("phase") or ""),
            str(run.get("ocr_status") or ""),
            int(run.get("game_count") or 0),
            int(run.get("cycle_num") or 0),
            str(run.get("terminal_reason") or ""),
            str(run.get("last_action") or ""),
            target=target,
            mode=mode,
            strategy=strategy,
        )
        if active and not self._runtime_active:
            self.showMinimized()
        elif not active and self._runtime_active:
            self.showNormal()
            self.raise_()
        self._runtime_active = active

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
        self.overlay_hud.close()
        self.tray.hide()
        event.accept()
