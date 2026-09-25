"""刷刷宝看板 · 桌面 UI 预览窗口（模拟数据，不连接游戏）。

- 用 Vite dev server（mock bridge）加载 ui-v2，窗口尺寸与正式宿主 WebConfigShell 一致：
  看板 960×820；蹭车/跟车小窗 360×页面实测高；向导 560×300 / 560×560，缩放固定 1.0。
- 窗口右侧附带「场景」面板：按钮直接调用页面里的 window.__sbPreview.run(id)
  （实现位于 ui-v2/src/dev/previewScenes.ts，与在线预览沙盒共用同一份）。
- 页面在 mock 桥里广播 sb:window-layout，previewScenes.ts 把它转成控制台行
  「[sb-preview-layout] {...}」，这里据此调整窗口尺寸，模拟正式宿主的大小窗切换。

用法：
  pythonw preview_window.py                      # 正常打开
  python  preview_window.py --snapshot out.png   # 打开后截图退出
  python  preview_window.py --snapshot out.png --scene hitch   # 先切到某个场景再截图
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

UI_ROOT = Path(__file__).resolve().parents[1]  # …/ui-v2
NODE = Path(r"C:\Program Files\nodejs\node.exe")
PORT = 5187
URL = f"http://127.0.0.1:{PORT}/index.html"

# 与 src/shuabao/shell/web_config_shell.py 保持一致。
DASHBOARD_SIZE = (960, 820)
CHOOSER_SOLO_SIZE = (560, 300)
CHOOSER_TEAM_SIZE = (560, 560)
COMPACT_WIDTH, COMPACT_MIN_HEIGHT, COMPACT_DEFAULT_HEIGHT = 360, 400, 640
LAYOUT_TAG = "[sb-preview-layout] "


def ready() -> bool:
    try:
        with urlopen(URL, timeout=1) as response:
            return response.status == 200 and "<title>刷刷宝看板</title>".encode() in response.read()
    except OSError:
        return False


def ensure_server() -> None:
    entry = UI_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    if not NODE.is_file() or not entry.is_file():
        raise RuntimeError(f"预览依赖不存在：请确认 {UI_ROOT} 下已 npm install，且本机安装了 Node.js。")
    if ready():
        return
    subprocess.Popen(
        [str(NODE), str(entry), "--host", "127.0.0.1", "--port", str(PORT), "--strictPort"],
        cwd=UI_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(60):
        if ready():
            return
        time.sleep(0.25)
    raise RuntimeError(f"本地预览服务未启动；{PORT} 端口可能被其他程序占用。")


class PreviewPage(QWebEnginePage):
    """接收页面发出的窗口尺寸请求（控制台行），转给窗口。"""

    def __init__(self, on_layout, parent=None):
        super().__init__(parent)
        self._on_layout = on_layout

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        if message.startswith(LAYOUT_TAG):
            try:
                detail = json.loads(message[len(LAYOUT_TAG):])
            except ValueError:
                return
            self._on_layout(str(detail.get("layout") or "dashboard"), detail.get("height"))


class PreviewWindow(QMainWindow):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.setWindowTitle("刷刷宝 · 看板预览（模拟数据，不连接游戏）")
        self.view = QWebEngineView(self)
        self.view.setPage(PreviewPage(self.apply_layout, self.view))
        self.view.setZoomFactor(1.0)
        self.setCentralWidget(self.view)
        self.setFixedSize(*DASHBOARD_SIZE)
        self.panel = ScenePanel(self)

    def apply_layout(self, layout: str, height=None) -> None:
        if layout == "compact":
            h = int(height or COMPACT_DEFAULT_HEIGHT)
            screen = self.screen()
            if screen is not None:
                h = min(h, screen.availableGeometry().height() - 48)
            size = (COMPACT_WIDTH, max(COMPACT_MIN_HEIGHT, h))
        elif layout == "chooser-solo":
            size = CHOOSER_SOLO_SIZE
        elif layout in {"chooser", "chooser-team"}:
            size = CHOOSER_TEAM_SIZE
        else:
            size = DASHBOARD_SIZE
        if (self.width(), self.height()) != size:
            self.setFixedSize(*size)
        self.panel.follow()

    def run_scene(self, scene_id: str) -> None:
        self.view.page().runJavaScript(
            "window.__sbPreview ? window.__sbPreview.run(%s) : console.warn('预览场景未就绪')" % json.dumps(scene_id)
        )

    def moveEvent(self, event):  # noqa: N802
        super().moveEvent(event)
        self.panel.follow()


class ScenePanel(QWidget):
    """贴在预览窗口右侧的场景按钮面板；按钮列表从页面的 window.__sbPreview.scenes 读取。"""

    def __init__(self, host: PreviewWindow):
        super().__init__(None, Qt.WindowType.Tool)
        self.host = host
        self.setWindowTitle("场景")
        self.setFixedWidth(236)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(10, 10, 10, 10)
        self.box.setSpacing(6)
        hint = QLabel("加载中…")
        hint.setWordWrap(True)
        self.box.addWidget(hint)

    def populate(self, scenes) -> None:
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        groups: dict[str, list[dict]] = {}
        for scene in scenes or []:
            groups.setdefault(scene.get("group", "其他"), []).append(scene)
        for name, items in groups.items():
            title = QLabel(name)
            title.setStyleSheet("color:#8b939e;font-weight:600;margin-top:4px;")
            self.box.addWidget(title)
            grid = QWidget()
            lay = QGridLayout(grid)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            for i, scene in enumerate(items):
                btn = QPushButton(scene.get("label", scene.get("id")))
                btn.clicked.connect(lambda _=False, sid=scene["id"]: self.host.run_scene(sid))
                lay.addWidget(btn, i // 2, i % 2)
            self.box.addWidget(grid)
        reload_btn = QPushButton("重新加载页面")
        reload_btn.clicked.connect(self.host.view.reload)
        self.box.addWidget(reload_btn)
        note = QLabel("全部是模拟数据；「运行中」会启动模拟运行，点「停止」或重新加载即可。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8b939e;")
        self.box.addWidget(note)
        self.box.addStretch(1)
        self.follow()

    def follow(self) -> None:
        geo = self.host.frameGeometry()
        self.move(geo.right() + 8, geo.top())
        self.setFixedHeight(max(420, self.host.height()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--scene")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    try:
        ensure_server()
    except Exception as exc:  # noqa: BLE001 - 预览工具直接提示
        QMessageBox.critical(None, "刷刷宝 UI 预览", str(exc))
        return 1

    window = PreviewWindow(app)

    def fetch_scenes(tries: int = 0) -> None:
        def got(value) -> None:
            if value:
                window.panel.populate(json.loads(value))
            elif tries < 40:
                QTimer.singleShot(250, lambda: fetch_scenes(tries + 1))
        window.view.page().runJavaScript(
            "window.__sbPreview ? JSON.stringify(window.__sbPreview.scenes) : ''", got
        )

    def loaded(ok: bool) -> None:
        if not ok:
            QMessageBox.critical(window, "刷刷宝 UI 预览", "看板页面加载失败。")
            return
        fetch_scenes()

    window.view.loadFinished.connect(loaded)
    window.view.load(QUrl(URL))
    window.show()
    if not args.snapshot:
        window.panel.show()

    if args.snapshot:
        target = args.snapshot

        def capture(ok: bool) -> None:
            if not ok:
                app.exit(2)
                return

            def shoot() -> None:
                def finish(metrics: str) -> None:
                    print(f"viewport={metrics}", flush=True)
                    app.exit(0 if window.view.grab().save(str(target)) else 3)

                window.view.page().runJavaScript(
                    "JSON.stringify({width:innerWidth,height:innerHeight,zoom:devicePixelRatio})", finish
                )

            def go() -> None:
                if args.scene:
                    window.run_scene(args.scene)
                    QTimer.singleShot(2500, shoot)
                else:
                    shoot()

            QTimer.singleShot(3500, go)

        window.view.loadFinished.connect(capture)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
