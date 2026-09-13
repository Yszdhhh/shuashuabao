"""Task 6：WebConfigShell（QWebEngine 宿主与生命周期集成，设计规格 §8/§9/§12）。

覆盖：
- QWebChannel 全程只注册 DashboardFacade 一个对象（§6.1 唯一注册对象）
- 导航拦截：非 file/qrc 一律拒绝；createWindow 弹新窗口拒绝；子资源兜底拦截
- closeEvent 安全触发：运行中先 runner.stop() 收尾；收不下来拒绝关闭
- renderProcessTerminated：崩溃只出原生错误页，不碰 RunnerService
- desktop_app 环境变量切换：默认/SHUABAO_SHELL=web → WebConfigShell，显式 native → MainWindow
- 入口纯净：desktop_app / web_config_shell 不引入 fastapi/uvicorn/webview/api_server
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtGui import QCloseEvent, QShortcut  # noqa: E402
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


@pytest.mark.parametrize("active", [True, False])
def test_packaged_subscription_check_uses_ui_slot_and_omits_secrets(tmp_path, monkeypatch, active):
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_LICENSE_KEY", "sensitive-test-key")
    facade = MagicMock()
    facade.activate_subscription.return_value = json.dumps({
        "ok": active, "status": "ACTIVE" if active else "DENIED",
        "expires_at": "2026-12-31", "message": "sensitive-test-key",
        "device_fingerprint": "private-device", "key": "sensitive-test-key",
    })
    path = tmp_path / "check.json"
    assert desktop_app._write_subscription_check_report(path, facade) is active
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["verified_tls"] is True
    assert report["ca_count"] > 0
    assert report["status"] == ("ACTIVE" if active else "DENIED")
    assert "sensitive-test-key" not in path.read_text(encoding="utf-8")
    assert "private-device" not in path.read_text(encoding="utf-8")
    facade.activate_subscription.assert_called_once_with(json.dumps({"key": "sensitive-test-key"}))
    facade.start_run.assert_not_called()


def test_packaged_tls_check_fails_closed_without_activating(tmp_path, monkeypatch):
    import ssl
    import shuabao.subscription_client as client

    def broken_context():
        raise ssl.SSLError(1, "private TLS details")

    monkeypatch.setattr(client, "_subscription_ssl_context", broken_context)
    facade = MagicMock()
    path = tmp_path / "check.json"
    assert desktop_app._write_subscription_check_report(path, facade) is False
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["error"] == "订阅自检失败: TLS 初始化/连接失败"
    facade.activate_subscription.assert_not_called()


def test_packaged_subscription_check_exits_failed_on_ui_slot_exception(tmp_path):
    facade = MagicMock()
    facade.activate_subscription.side_effect = RuntimeError("sensitive-test-key")
    path = tmp_path / "check.json"
    assert desktop_app._write_subscription_check_report(path, facade) is False
    assert json.loads(path.read_text(encoding="utf-8"))["error"] == "订阅自检失败: RuntimeError"


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
    s.close()
    s.deleteLater()
    qapp.processEvents()


def _new_shell(tmp_path: Path, runner=None) -> WebConfigShell:
    return WebConfigShell(
        tmp_path, ROOT, dist_dir=_make_dist(tmp_path), runner=runner or _FakeRunner()
    )

def test_host_window_matches_od12_product_size(shell):
    """宿主=产品窗 1080×820：独立看板，无画布黑边。"""
    assert (shell.width(), shell.height()) == (1080, 820)


def test_wizard_layout_uses_content_sized_solo_and_team_windows(shell):
    shell._set_window_layout("chooser-solo")
    assert (shell.width(), shell.height()) == (560, 300)
    shell._set_window_layout("chooser-team")
    assert (shell.width(), shell.height()) == (560, 560)
    # Legacy callers that only know chooser retain the team-sized contract.
    shell._set_window_layout("chooser")
    assert (shell.width(), shell.height()) == (560, 560)
    region = shell._titlebar_drag_region
    assert (region.x(), region.y(), region.width(), region.height()) == (0, 0, 330, 40)
    shell._set_window_layout("dashboard")
    assert (shell.width(), shell.height()) == (1080, 820)


def test_compact_layout_is_360_wide_content_high_and_keeps_window_buttons(shell):
    """蹭车/跟车二级小窗：宽 360、高=页面实测值；拖动区不盖住右侧最小化/关闭。"""
    shell._set_window_layout("compact", height=642)
    assert (shell.width(), shell.height()) == (360, 642)
    region = shell._titlebar_drag_region
    assert (region.x(), region.y(), region.width(), region.height()) == (0, 0, 264, 40)
    # 过矮的实测值抬到下限，不会把窗口压扁。
    shell._set_window_layout("compact", height=100)
    assert (shell.width(), shell.height()) == (360, 400)
    shell._set_window_layout("dashboard")
    assert (shell.width(), shell.height()) == (1080, 820)
    assert shell._titlebar_drag_region.width() == 850


def test_runtime_uses_only_the_full_mode_wizard():
    """快速开局和底部切换入口必须共用完整向导，不能再走另一套简版 chooser。"""
    html = (ROOT / "ui-v2" / "index.html").read_text(encoding="utf-8")
    assert "chooser-body" not in html
    assert "renderChooserKind" not in html
    assert '$("btnSwitchMode").addEventListener("click",openWizard)' in html
    assert '$("btnWizard").addEventListener("click",openWizard)' in html


def test_frameless_titlebar_drag_region_receives_native_mouse_press(shell, monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(shell, "_begin_window_drag", lambda: calls.append(True))

    class _Press:
        def button(self):
            return Qt.MouseButton.LeftButton

        def accept(self):
            calls.append(False)

    region = shell._titlebar_drag_region
    assert (region.x(), region.y(), region.width(), region.height()) == (0, 0, 690, 40)
    region.mousePressEvent(_Press())
    assert calls == [True, False]


def test_production_canvas_semantics_host_exact_product_window():
    """生产态：body 只保留居中语义；折叠断点必须低于固定视口 1080。"""
    html = (ROOT / "ui-v2" / "index.html").read_text(encoding="utf-8")
    assert "place-items: center;" in html
    assert "padding: 24px 16px;" not in html, "生产态不得残留沙盒画布留白"
    assert "@media (max-width: 920px)" not in html, "920 断点会在固定视口误触发单列"
    assert "@media (max-width: 860px)" in html
    assert 'body[data-scene="wizard"] {\n      display: flex;' in html
    assert 'body[data-scene="wizard"] .wiz {\n      width: 100%; height: 100%;' in html
    assert 'background: oklch(0.955 0.008 250); padding: 0; overflow: hidden;' in html
    assert '--p-radius: 8px;' in html
    assert 'border: 1px solid var(--p-line); border-radius: 12px;' in html
    assert 'box-shadow: var(--p-shadow)' in html
    assert 'grid-template-columns: minmax(0, 1fr); place-items: center; text-align: center;' in html
    assert 'id="summary"' not in html, "生产底栏不得再渲染重复摘要"
    assert 'cjb:"03洛卡纳哈"' in html
    assert 'const MODE_LABEL = { solo:"单人模式", lead:"组队带车模式", follow:"组队跟车模式", hitch:"组队蹭车模式" };' in html


def test_stage_choice_preserves_explicit_boss_choices():
    """关卡选择只改 stage_targets；Boss/传家宝保持用户的显式选择。"""
    html = (ROOT / "ui-v2" / "index.html").read_text(encoding="utf-8")
    bridge = (ROOT / "ui-v2" / "src" / "main.ts").read_text(encoding="utf-8")

    assert "recommendChallenges" not in html
    assert "STAGE_BOSS" not in html
    assert "STAGE_CJB" not in html
    assert "recommendChallenges" not in bridge
    assert "if (cjb) state.cjb = cjb;" in bridge
    assert "if (boss) state.boss = boss;" in bridge
    assert "renderNames();" in bridge


def test_webengine_view_uses_widget_safe_border_reset():
    """QWebEngineView is a QWidget; use its margins/style instead of QFrame APIs."""
    source = (ROOT / "src" / "shuabao" / "shell" / "web_config_shell.py").read_text(encoding="utf-8")
    assert "setFrameShape" not in source
    assert 'setContentsMargins(0, 0, 0, 0)' in source


def test_desktop_web_launcher_defaults_to_isolated_app_data():
    """Web 预览默认隔离，只有显式环境覆盖时才可能共用正式数据。"""
    text = (ROOT / "tools" / "launch_web_shell.vbs").read_text(encoding="utf-8")
    assert "SHUABAO_SHELL" in text
    assert "SHUABAO_APP_DATA" in text
    assert "ShuaBaoWeb" in text
    assert 'If appData = "" Then' in text


def _sign_packaged_subscription_config(monkeypatch, package_root, *, manifest_channel=None):
    """Temporary test keys authenticate a synthetic bundle; no runtime key file."""
    import base64
    import hashlib
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from shuabao import release_signing

    private = Ed25519PrivateKey.generate()
    sidecar = package_root / "subscription_runtime.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
    manifest = {
        "schema_version": 1,
        "source_sha": "a" * 40,
        "release_channel": manifest_channel or payload.get("release_channel") or "dev",
        "files": [
            {"path": path.name, "size_bytes": path.stat().st_size,
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in (package_root / "ShuaBao.exe", sidecar) if path.exists()
        ],
    }
    (package_root / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (package_root / "release_manifest.json.sig").write_text(json.dumps({
        "schema_version": 1, "algorithm": "Ed25519", "key_id": "temporary-manifest-test",
        "manifest_sha256": release_signing.canonical_manifest_sha256(manifest),
        "signature": base64.urlsafe_b64encode(private.sign(
            release_signing.canonical_manifest_bytes(manifest),
        )).decode().rstrip("="),
    }), encoding="utf-8")
    monkeypatch.setattr(release_signing, "PINNED_MANIFEST_PUBLIC_KEYS", {
        "temporary-manifest-test": private.public_key(),
    })


def test_frozen_entry_loads_non_secret_subscription_sidecar(monkeypatch, tmp_path):
    sidecar = tmp_path / "subscription_runtime.json"
    sidecar.write_text(
        json.dumps({"schema_version": 1, "release_channel": "dev", "base_url": "https://license.example", "mode": "enforce", "timeout_s": 2}),
        encoding="utf-8",
    )
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe), raising=False)
    monkeypatch.delenv("SHUABAO_SUBSCRIPTION_BASE_URL", raising=False)
    monkeypatch.delenv("SHUABAO_SUBSCRIPTION_MODE", raising=False)
    monkeypatch.delenv("SHUABAO_SUBSCRIPTION_TIMEOUT_S", raising=False)

    _sign_packaged_subscription_config(monkeypatch, tmp_path)
    desktop_app._load_packaged_subscription_config(tmp_path)

    assert os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] == "https://license.example"
    assert os.environ["SHUABAO_SUBSCRIPTION_MODE"] == "enforce"
    assert os.environ["SHUABAO_SUBSCRIPTION_TIMEOUT_S"] == "2"
    # The function intentionally writes process-level deployment settings;
    # explicitly undo them so this test remains isolated when desktop tests
    # are selected together in a different order.
    for name in (
        "SHUABAO_SUBSCRIPTION_BASE_URL",
        "SHUABAO_SUBSCRIPTION_MODE",
        "SHUABAO_SUBSCRIPTION_TIMEOUT_S",
    ):
        os.environ.pop(name, None)
def test_external_channel_ignores_environment_mode_and_pins_sidecar_url(monkeypatch, tmp_path):
    sidecar = tmp_path / "subscription_runtime.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_url": "https://license.example",
                "mode": "enforce",
                "release_channel": "external-beta",
            }
        ),
        encoding="utf-8",
    )
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe), raising=False)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "off")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_BASE_URL", "http://127.0.0.1:9999")

    _sign_packaged_subscription_config(monkeypatch, tmp_path)
    desktop_app._load_packaged_subscription_config(tmp_path)

    assert os.environ["SHUABAO_SUBSCRIPTION_MODE"] == "enforce"
    assert os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] == "https://license.example"


def test_external_channel_rejects_non_enforce_or_secret_sidecar(monkeypatch, tmp_path):
    sidecar = tmp_path / "subscription_runtime.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_url": "https://license.example",
                "mode": "off",
                "release_channel": "release",
                "license_key": "card-secret-must-not-load",
            }
        ),
        encoding="utf-8",
    )
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe), raising=False)
    monkeypatch.delenv("SHUABAO_SUBSCRIPTION_MODE", raising=False)
    monkeypatch.delenv("SHUABAO_SUBSCRIPTION_LICENSE_KEY", raising=False)

    _sign_packaged_subscription_config(monkeypatch, tmp_path)
    desktop_app._load_packaged_subscription_config(tmp_path)

    assert os.environ["SHUABAO_SUBSCRIPTION_MODE"] == "enforce"
    assert os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] == "invalid-packaged-subscription-url"
    assert "SHUABAO_SUBSCRIPTION_LICENSE_KEY" not in os.environ

def test_external_empty_sidecar_url_rejects_environment_url(monkeypatch, tmp_path):
    from shuabao.subscription_client import check_start_permission

    sidecar = tmp_path / "subscription_runtime.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_url": "",
                "mode": "enforce",
                "release_channel": "external-beta",
            }
        ),
        encoding="utf-8",
    )
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe), raising=False)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_BASE_URL", "https://attacker.example")

    _sign_packaged_subscription_config(monkeypatch, tmp_path)
    desktop_app._load_packaged_subscription_config(tmp_path)
    permission = check_start_permission(
        env=dict(os.environ),
        opener=lambda *_args, **_kwargs: pytest.fail("invalid external URL must not reach network"),
    )

    assert permission.allowed is False
    assert permission.code == "CONFIG_BASE_URL_INVALID"


def test_external_empty_sidecar_url_rejects_default_loopback(monkeypatch, tmp_path):
    from shuabao.subscription_client import check_start_permission

    sidecar = tmp_path / "subscription_runtime.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_url": "",
                "mode": "enforce",
                "release_channel": "release",
            }
        ),
        encoding="utf-8",
    )
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe), raising=False)
    monkeypatch.delenv("SHUABAO_SUBSCRIPTION_BASE_URL", raising=False)
    monkeypatch.delenv("SHUABAO_SUBSCRIPTION_MODE", raising=False)

    _sign_packaged_subscription_config(monkeypatch, tmp_path)
    desktop_app._load_packaged_subscription_config(tmp_path)
    permission = check_start_permission(
        env=dict(os.environ),
        opener=lambda *_args, **_kwargs: pytest.fail("invalid external URL must not reach network"),
    )

    assert permission.allowed is False
    assert permission.code == "CONFIG_BASE_URL_INVALID"


@pytest.mark.parametrize("release_channel", [None, "unrecognized"])
def test_frozen_missing_or_unknown_channel_defaults_to_enforce(monkeypatch, tmp_path, release_channel):
    payload = {
        "schema_version": 1,
        "base_url": "https://license.example",
        "mode": "off",
    }
    if release_channel is not None:
        payload["release_channel"] = release_channel
    sidecar = tmp_path / "subscription_runtime.json"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe), raising=False)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "shadow")

    _sign_packaged_subscription_config(monkeypatch, tmp_path)
    desktop_app._load_packaged_subscription_config(tmp_path)

    assert os.environ["SHUABAO_SUBSCRIPTION_MODE"] == "enforce"

def test_frozen_missing_sidecar_defaults_to_enforce(monkeypatch, tmp_path):
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe), raising=False)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "shadow")

    _sign_packaged_subscription_config(monkeypatch, tmp_path)
    desktop_app._load_packaged_subscription_config(tmp_path)

    assert os.environ["SHUABAO_SUBSCRIPTION_MODE"] == "enforce"


@pytest.mark.parametrize("release_channel", ["dev", "internal-pilot"])
def test_diagnostic_channels_use_verified_config_over_environment(monkeypatch, tmp_path, release_channel):
    sidecar = tmp_path / "subscription_runtime.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_url": "https://license.example",
                "mode": "enforce",
                "release_channel": release_channel,
            }
        ),
        encoding="utf-8",
    )
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"stub")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe), raising=False)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "off")

    _sign_packaged_subscription_config(monkeypatch, tmp_path)
    desktop_app._load_packaged_subscription_config(tmp_path)

    assert os.environ["SHUABAO_SUBSCRIPTION_MODE"] == "enforce"
    assert os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] == "https://license.example"
    assert os.environ["SHUABAO_SUBSCRIPTION_TIMEOUT_S"] == "10"


@pytest.mark.parametrize("channel", ["dev", "internal-pilot", "external-beta", "release"])
def test_all_frozen_channels_override_stale_endpoint_mode_and_timeout(monkeypatch, tmp_path, channel):
    sidecar = tmp_path / "subscription_runtime.json"
    sidecar.write_text(json.dumps({
        "schema_version": 1, "release_channel": channel,
        "base_url": "https://license.example", "mode": "enforce", "timeout_s": 10,
    }), encoding="utf-8")
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"synthetic-test-bundle")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe))
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_BASE_URL", "https://stale.example")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "off")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_TIMEOUT_S", "0.5")
    _sign_packaged_subscription_config(monkeypatch, tmp_path)

    desktop_app._load_packaged_subscription_config(tmp_path)

    assert os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] == "https://license.example"
    assert os.environ["SHUABAO_SUBSCRIPTION_MODE"] == "enforce"
    assert os.environ["SHUABAO_SUBSCRIPTION_TIMEOUT_S"] == "10"


@pytest.mark.parametrize("damage", [
    "missing-signature", "tampered-sidecar", "unknown-key", "channel-mismatch",
    "invalid-timeout", "invalid-schema", "empty-url", "remote-http",
    "unknown-field", "non-enforce-mode",
])
def test_invalid_frozen_config_blocks_network_and_environment_fallback(monkeypatch, tmp_path, damage):
    from shuabao import release_signing
    from shuabao.subscription_client import validate_entitlement

    payload = {"schema_version": 1, "release_channel": "dev",
               "base_url": "https://license.example", "mode": "enforce", "timeout_s": 10}
    if damage == "invalid-timeout":
        payload["timeout_s"] = -1
    elif damage == "invalid-schema":
        payload["schema_version"] = 2
    elif damage == "empty-url":
        payload["base_url"] = ""
    elif damage == "remote-http":
        payload["base_url"] = "http://license.example"
    elif damage == "unknown-field":
        payload["license_key"] = "must-never-enter-a-frozen-sidecar"
    elif damage == "non-enforce-mode":
        payload["mode"] = "off"
    sidecar = tmp_path / "subscription_runtime.json"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"synthetic-test-bundle")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe))
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_BASE_URL", "https://stale.example")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "off")
    _sign_packaged_subscription_config(
        monkeypatch, tmp_path, manifest_channel="release" if damage == "channel-mismatch" else None,
    )
    if damage == "missing-signature":
        (tmp_path / "release_manifest.json.sig").unlink()
    elif damage == "tampered-sidecar":
        payload["base_url"] = "https://tampered.example"
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
    elif damage == "unknown-key":
        monkeypatch.setattr(release_signing, "PINNED_MANIFEST_PUBLIC_KEYS", {})

    desktop_app._load_packaged_subscription_config(tmp_path)
    result = validate_entitlement(
        "temporary-test-license", env=dict(os.environ),
        opener=lambda *_args, **_kwargs: pytest.fail("untrusted configuration must not reach network"),
    )

    assert os.environ["SHUABAO_SUBSCRIPTION_MODE"] == "enforce"
    assert result["valid"] is False
    assert result["code"] == "CONFIG_BASE_URL_INVALID"


def test_frozen_config_uses_verified_bytes_without_rereading_sidecar(monkeypatch, tmp_path):
    sidecar = tmp_path / "subscription_runtime.json"
    payload = {"schema_version": 1, "release_channel": "dev",
               "base_url": "https://license.example", "mode": "enforce", "timeout_s": 10}
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    exe = tmp_path / "ShuaBao.exe"
    exe.write_bytes(b"synthetic-test-bundle")
    monkeypatch.setattr(desktop_app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop_app.sys, "executable", str(exe))
    _sign_packaged_subscription_config(monkeypatch, tmp_path)
    verify = desktop_app.verify_packaged_release_snapshot

    def verify_then_replace(*args, **kwargs):
        result = verify(*args, **kwargs)
        sidecar.write_text(json.dumps({**payload, "base_url": "https://tampered.example"}), encoding="utf-8")
        return result

    monkeypatch.setattr(desktop_app, "verify_packaged_release_snapshot", verify_then_replace)
    desktop_app._load_packaged_subscription_config(tmp_path)

    assert os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] == "https://license.example"


def test_source_entry_keeps_development_environment_without_reading_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop_app.sys, "frozen", False, raising=False)
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "off")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_BASE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_TIMEOUT_S", "2")
    monkeypatch.setattr(desktop_app, "verify_packaged_release_snapshot", lambda *_a, **_k: pytest.fail("source mode must not read a bundle"))

    desktop_app._load_packaged_subscription_config(tmp_path)

    assert os.environ["SHUABAO_SUBSCRIPTION_MODE"] == "off"
    assert os.environ["SHUABAO_SUBSCRIPTION_BASE_URL"] == "http://127.0.0.1:8765"
    assert os.environ["SHUABAO_SUBSCRIPTION_TIMEOUT_S"] == "2"


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
        s.close()
        s.deleteLater()
        qapp.processEvents()


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
    assert shell.profile.parent() is None, "profile 必须晚于 page/view 析构，防 Python 3.13 退出访问冲突"
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


def test_tray_stop_and_f12_shortcuts_use_shared_runner(shell):
    menu = shell.tray.contextMenu()
    stop_action = next(action for action in menu.actions() if action.text() == "停止运行")
    stop_action.trigger()
    shortcuts = {shortcut.key().toString(): shortcut for shortcut in shell.findChildren(QShortcut)}
    assert {"F12", "Shift+F12"} <= set(shortcuts)
    shortcuts["F12"].activated.emit()
    shortcuts["Shift+F12"].activated.emit()
    assert shell.runner.stop_calls == 3


def test_tray_quit_uses_close_safety_chain(qapp, tmp_path):
    s = _new_shell(tmp_path)
    try:
        menu = s.tray.contextMenu()
        quit_action = next(action for action in menu.actions() if action.text() == "退出")
        quit_action.trigger()
        qapp.processEvents()
        assert s.runner.stop_calls == 1
        assert s.runner.release_calls == 1
    finally:
        s.close()
        s.deleteLater()
        qapp.processEvents()


def test_runtime_status_anchors_hud_to_shared_worker_mediator(shell, monkeypatch):
    frame = object()
    shell.runner.worker.mediator = type("_Mediator", (), {"_last_frame": frame})()
    anchored: list[object] = []
    monkeypatch.setattr(shell.overlay_hud, "anchor_to_target", anchored.append)
    shell._on_runtime_status(
        json.dumps({"state": "RUNNING", "mode_id": "normal_farm", "phase": "FARM"})
    )
    assert anchored == [frame]


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
        s.runner.worker._stuck = False
        s.runner.worker.running = False
        s.close()
        s.deleteLater()
        qapp.processEvents()


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


def test_resolve_dist_index_rejects_stale_manifest(tmp_path):
    dist = tmp_path / "ui-v2" / "dist"
    dist.mkdir(parents=True)
    index = dist / "index.html"
    index.write_text("<html>current</html>", encoding="utf-8")
    (dist / "build_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "source_sha": "source-a",
        "index_sha256": "0" * 64,
    }), encoding="utf-8")
    with pytest.raises(RuntimeError, match="index.html"):
        resolve_dist_index(tmp_path)


def test_resolve_dist_index_rejects_source_sha_mismatch(tmp_path):
    dist = tmp_path / "ui-v2" / "dist"
    dist.mkdir(parents=True)
    index = dist / "index.html"
    index.write_text("<html>current</html>", encoding="utf-8")
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    (tmp_path / "build_identity.json").write_text(json.dumps({"source_sha": "current-sha"}), encoding="utf-8")
    (dist / "build_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "source_sha": "stale-sha",
        "index_sha256": digest,
        "bridge_schema_version": 2,
    }), encoding="utf-8")
    with pytest.raises(RuntimeError, match="源码提交不一致"):
        resolve_dist_index(tmp_path)


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


# ------------------------------------------------------ desktop_app 正式入口（§9）


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


def test_entry_uses_the_web_dashboard_by_default(tmp_path):
    mw, wc = _run_main(tmp_path, "web")
    wc.assert_called_once()
    kwargs = wc.call_args.kwargs
    assert Path(kwargs["app_data"]) == tmp_path
    assert Path(kwargs["root"]) == desktop_app.ROOT
    mw.assert_not_called()


@pytest.mark.parametrize(
    ("env_value", "uses_web"),
    ((None, True), ("web", True), ("native", False), ("NATIVE", False), ("weird", True)),
)
def test_entry_uses_web_dashboard_except_explicit_native_compatibility(tmp_path, env_value, uses_web):
    """正式版固定 Web；只有显式 native 才能进入历史兼容看板。"""
    mw, wc = _run_main(tmp_path, env_value)
    if uses_web:
        wc.assert_called_once()
        mw.assert_not_called()
    else:
        mw.assert_called_once_with(app_data=tmp_path)
        wc.assert_not_called()


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
