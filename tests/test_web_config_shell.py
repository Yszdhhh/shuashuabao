"""Task 6：WebConfigShell（QWebEngine 宿主与生命周期集成，设计规格 §8/§9/§12）。

覆盖：
- QWebChannel 全程只注册 DashboardFacade 一个对象（§6.1 唯一注册对象）
- 导航拦截：非 file/qrc 一律拒绝；createWindow 弹新窗口拒绝；子资源兜底拦截
- closeEvent 安全触发：运行中先 runner.stop() 收尾；收不下来拒绝关闭
- renderProcessTerminated：崩溃只出原生错误页，不碰 RunnerService
- desktop_app 环境变量切换：SHUABAO_SHELL=web → WebConfigShell，默认/其它 → MainWindow
- 入口纯净：desktop_app / web_config_shell 不引入 fastapi/uvicorn/webview/api_server
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import desktop_app  # noqa: E402
from shuabao.shell.dashboard_facade import DashboardFacade  # noqa: E402
import shuabao.shell.web_config_shell as wcs  # noqa: E402
from shuabao.shell.web_config_shell import (  # noqa: E402
    ALLOWED_SCHEMES,
    LocalOnlyPage,
    QWebChannel,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    WebConfigShell,
    resolve_dist_index,
)

WEBENGINE_MODULES = (
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
)


# ---------------------------------------------------------------- 夹具与假件


class _FakeWorker:
    def __init__(self, stuck: bool = False):
        self.running = True
        self.stop_called = False
        self._stuck = stuck

    def isRunning(self) -> bool:  # noqa: N802
        return self.running

    def stop(self) -> None:
        self.stop_called = True
        if not self._stuck:
            self.running = False

    def wait(self, msecs: int) -> bool:
        return not self._stuck


class _FakeRunner:
    """形状与 RunnerService 兼容的最小替身：worker / stop / release_after_finish。"""

    def __init__(self, worker: _FakeWorker | None = None):
        self.worker = worker if worker is not None else _FakeWorker()
        self.stop_calls = 0
        self.release_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1
        self.worker.stop()

    def release_after_finish(self) -> None:
        self.release_calls += 1


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_dist(tmp_path: Path) -> Path:
    """最小本地构建产物：真实 file:// 加载目标，避免拉起完整前端。"""
    dist = tmp_path / "ui-v2" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    return dist


@pytest.fixture()
def shell(qapp, tmp_path):
    s = WebConfigShell(
        tmp_path, ROOT, dist_dir=_make_dist(tmp_path), runner=_FakeRunner()
    )
    yield s
    s.deleteLater()


def _new_shell(tmp_path: Path, runner=None) -> WebConfigShell:
    return WebConfigShell(
        tmp_path, ROOT, dist_dir=_make_dist(tmp_path), runner=runner or _FakeRunner()
    )

def test_host_window_matches_od12_product_size(shell):
    """宿主=产品窗 920×720：独立看板，无画布黑边。"""
    assert (shell.width(), shell.height()) == (920, 720)


def test_production_canvas_semantics_host_exact_product_window():
    """生产态：body 只保留居中语义；折叠断点必须低于固定视口 920。"""
    html = (ROOT / "ui-v2" / "index.html").read_text(encoding="utf-8")
    assert "place-items: center;" in html
    assert "padding: 24px 16px;" not in html, "生产态不得残留沙盒画布留白"
    assert "@media (max-width: 920px)" not in html, "920 断点会在固定视口误触发单列"
    assert "@media (max-width: 860px)" in html


def test_desktop_web_launcher_uses_canonical_app_data():
    """正式 Web 入口与原生看板共享 Settings/单实例锁，不再用 ShuaBaoWeb 沙盒。"""
    text = (ROOT / "tools" / "launch_web_shell.vbs").read_text(encoding="utf-8")
    assert "SHUABAO_SHELL" in text
    assert "SHUABAO_APP_DATA" not in text


# ---------------------------------------------------- QWebChannel 唯一注册（§6.1）


def test_qwebchannel_registers_only_facade(qapp, tmp_path, monkeypatch):
    calls: list[tuple[str, object]] = []
    original = QWebChannel.registerObject

    def spy(self, name, obj):
        calls.append((name, obj))
        return original(self, name, obj)

    monkeypatch.setattr(QWebChannel, "registerObject", spy)
    s = _new_shell(tmp_path)
    try:
        assert calls == [("facade", s.facade)], "除 DashboardFacade 外禁止任何注册"
        assert isinstance(s.facade, DashboardFacade)
        assert s.page.webChannel() is s.channel
    finally:
        s.deleteLater()


# ------------------------------------------------------------ 导航拦截（§8）


def test_navigation_whitelist_allows_only_local_schemes(qapp):
    profile = QWebEngineProfile()
    page = LocalOnlyPage(profile)
    typed = QWebEnginePage.NavigationType.NavigationTypeTyped
    try:
        assert page.acceptNavigationRequest(
            QUrl("file:///C:/app/ui-v2/dist/index.html"), typed, True
        )
        assert page.acceptNavigationRequest(
            QUrl("qrc:///qtwebchannel/qwebchannel.js"), typed, True
        )
        remote = [
            "https://example.com/x",
            "http://example.com/",
            "javascript:alert(1)",
            "data:text/html,<b>x</b>",
            "ftp://host/file",
        ]
        for url in remote:
            assert not page.acceptNavigationRequest(QUrl(url), typed, True), url
        expected = [QUrl(u).toString() for u in remote]
        assert page.blocked_urls == expected
    finally:
        page.deleteLater()
        profile.deleteLater()


def test_create_window_always_rejected(qapp):
    profile = QWebEngineProfile()
    page = LocalOnlyPage(profile)
    try:
        for kind in (
            QWebEnginePage.WebWindowType.WebBrowserWindow,
            QWebEnginePage.WebWindowType.WebBrowserTab,
            QWebEnginePage.WebWindowType.WebDialog,
        ):
            assert page.createWindow(kind) is None
        assert len(page.blocked_urls) == 3
    finally:
        page.deleteLater()
        profile.deleteLater()


def test_request_interceptor_blocks_remote_subresources():
    interceptor = wcs._LocalOnlyRequestInterceptor()
    blocked: list[bool] = []

    class _Info:
        def __init__(self, url: str):
            self._url = QUrl(url)

        def requestUrl(self):  # noqa: N802
            return self._url

        def block(self, value: bool) -> None:
            blocked.append(value)

    interceptor.interceptRequest(_Info("https://cdn.example.com/app.js"))
    interceptor.interceptRequest(_Info("wss://telemetry.example.com"))
    interceptor.interceptRequest(_Info("qrc:///qtwebchannel/qwebchannel.js"))
    interceptor.interceptRequest(_Info("file:///C:/app/assets/logo.png"))
    assert blocked == [True, True], "远程子资源必须被 block，本地资源放行"


def test_allowed_schemes_are_exactly_file_and_qrc():
    assert ALLOWED_SCHEMES == {"file", "qrc"}


def test_profile_hardening(qapp, shell):
    settings = shell.profile.settings()
    # Qt6 起开发者工具默认关闭（DeveloperExtrasEnabled 已移除）；收紧其余面。
    assert not settings.testAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls
    )
    assert not settings.testAttribute(
        QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows
    )
    assert not settings.testAttribute(
        QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard
    )

# ------------------------------------------------------ 渲染崩溃隔离（§8）


def test_render_crash_shows_native_error_and_spares_runner(shell):
    status = QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus
    shell.page.renderProcessTerminated.emit(status, 1)
    runner: _FakeRunner = shell.runner
    assert shell._crash_overlay is not None and not shell._crash_overlay.isHidden()


def test_native_runtime_chrome_stops_through_shared_runner(shell):
    shell.overlay_hud.stop_requested.emit()
    assert shell.runner.stop_calls == 1


# ------------------------------------------------------ closeEvent 安全链（§9）


def test_close_stops_running_worker_then_accepts(shell):
    ev = QCloseEvent()
    shell.closeEvent(ev)
    runner: _FakeRunner = shell.runner
    assert ev.isAccepted()
    assert runner.stop_calls == 1
    assert runner.worker.stop_called
    assert runner.release_calls == 1


def test_close_refused_while_worker_cannot_finish(qapp, tmp_path):
    s = _new_shell(tmp_path, runner=_FakeRunner(worker=_FakeWorker(stuck=True)))
    try:
        ev = QCloseEvent()
        s.closeEvent(ev)
        assert not ev.isAccepted(), "worker 收不了尾时窗口不得关闭"
        assert s.runner.stop_calls == 1
    finally:
        s.deleteLater()


def test_close_with_idle_worker_accepts_immediately(shell):
    shell.runner.worker = None
    ev = QCloseEvent()
    shell.closeEvent(ev)
    assert ev.isAccepted()
    assert shell.runner.stop_calls == 0


# ------------------------------------------------------ 构建产物定位（§11）


def test_resolve_dist_index_dev_then_packaged(tmp_path):
    dev = tmp_path / "ui-v2" / "dist" / "index.html"
    dev.parent.mkdir(parents=True)
    dev.write_text("<html></html>", encoding="utf-8")
    assert resolve_dist_index(tmp_path) == dev.resolve()

    packaged_root = tmp_path / "pkg"
    web_dist = packaged_root / "web" / "dist" / "index.html"
    web_dist.parent.mkdir(parents=True)
    web_dist.write_text("<html></html>", encoding="utf-8")
    assert resolve_dist_index(packaged_root) == web_dist.resolve()

    with pytest.raises(FileNotFoundError):
        resolve_dist_index(tmp_path / "nowhere")


def test_missing_webengine_raises_loudly(monkeypatch):
    """缺 QtWebEngine 时显式 ModuleNotFoundError，绝不静默回退原生（§8）。"""
    spec = importlib.util.spec_from_file_location("_wcs_missing_webengine", wcs.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as m:
        for name in WEBENGINE_MODULES:
            m.setitem(sys.modules, name, None)
        with pytest.raises(ModuleNotFoundError):
            spec.loader.exec_module(module)


# ------------------------------------------------------ desktop_app 环境切换（§9）


def _run_main(tmp_path: Path, env_value: str | None):
    fake_app = MagicMock()
    fake_app.exec.return_value = 0
    fake_lock = MagicMock()
    fake_lock.tryLock.return_value = True
    fake_window = MagicMock()
    web_shell_mock = MagicMock(return_value=fake_window)
    native_mock = MagicMock(return_value=fake_window)
    # main() 在分支内延迟导入 WebConfigShell；用桩模块截获该导入。
    stub_module = SimpleNamespace(WebConfigShell=web_shell_mock)

    old = os.environ.pop("SHUABAO_SHELL", None)
    if env_value is not None:
        os.environ["SHUABAO_SHELL"] = env_value
    try:
        with (
            patch.object(desktop_app, "QApplication", return_value=fake_app),
            patch.object(desktop_app, "QLockFile", return_value=fake_lock),
            patch.object(desktop_app, "MainWindow", native_mock),
            patch.dict(sys.modules, {"shuabao.shell.web_config_shell": stub_module}),
            patch.object(desktop_app, "APP_DATA", tmp_path),
            patch.object(desktop_app.sys, "exit"),
        ):
            desktop_app.main()
    finally:
        os.environ.pop("SHUABAO_SHELL", None)
        if old is not None:
            os.environ["SHUABAO_SHELL"] = old
    return native_mock, web_shell_mock


def test_entry_web_env_uses_web_shell(tmp_path):
    mw, wc = _run_main(tmp_path, "web")
    wc.assert_called_once()
    kwargs = wc.call_args.kwargs
    assert Path(kwargs["app_data"]) == tmp_path
    assert Path(kwargs["root"]) == desktop_app.ROOT
    mw.assert_not_called()


def test_entry_default_and_unknown_env_keep_native(tmp_path):
    for env_value in (None, "native", "NATIVE", "weird"):
        mw, wc = _run_main(tmp_path, env_value)
        mw.assert_called_once()
        wc.assert_not_called(), f"SHUABAO_SHELL={env_value!r} 不得误入 Web 壳"
        mw.reset_mock()
        wc.reset_mock()


# ------------------------------------------------------ 入口纯净（§9/§12）


def test_entry_modules_never_import_forbidden_servers():
    forbidden = ("fastapi", "uvicorn", "pywebview", "api_server")
    sources = (
        ROOT / "desktop_app.py",
        ROOT / "src" / "shuabao" / "shell" / "web_config_shell.py",
    )
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for word in forbidden:
            assert word not in text, f"{path.name} 引用了禁用组件 {word}"
