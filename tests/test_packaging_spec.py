"""打包配置静态契约：ShuaBao.spec 与 requirements-desktop.txt。

不真正跑 PyInstaller，只验证 spec 源码里的关键声明：
web 前端产物被打进包、WebEngine 模块被 hiddenimports 兜底、
旧的 HTTP/WebView 依赖仍然被排除。
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _spec_text() -> str:
    return (PROJECT_ROOT / "ShuaBao.spec").read_text(encoding="utf-8")


def test_spec_bundles_web_dist() -> None:
    text = _spec_text()
    assert 'PROJECT_ROOT / "ui-v2" / "dist"' in text
    assert '"web"' in text and '"dist"' in text
    assert '"web" / "dist"' not in text, "打包目标必须是路径字符串，不能对 str 做 / 运算"


def test_spec_hiddenimports_include_qtwebengine_modules() -> None:
    text = _spec_text()
    for module in (
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel",
    ):
        assert module in text, f"hiddenimports missing {module}"


def test_spec_excludes_legacy_http_and_webview_backends() -> None:
    text = _spec_text()
    assert 'excludes=["fastapi", "uvicorn", "webview"]' in text


def test_requirements_desktop_use_full_pyside6() -> None:
    req = (PROJECT_ROOT / "requirements-desktop.txt").read_text(encoding="utf-8")
    assert not any(
        line.strip().startswith("PySide6-Essentials") for line in req.splitlines()
    )
    assert any(line.startswith("PySide6>=") for line in req.splitlines())


def test_build_script_rebuilds_ui_before_pyinstaller() -> None:
    text = (PROJECT_ROOT / "build_release.ps1").read_text(encoding="utf-8")
    assert "& $npm.Source ci" in text
    assert "& $npm.Source run build" in text
    assert text.index("& $npm.Source run build") < text.index("PyInstaller 打包")


def test_packaged_web_launcher_selects_web_shell_and_isolated_data() -> None:
    text = (PROJECT_ROOT / "tools" / "launch_packaged_web_shell.vbs").read_text(encoding="utf-8")
    assert '"SHUABAO_SHELL") = "web"' in text
    assert "ShuaBaoWeb" in text
    assert 'ShellExecute root & "\\ShuaBao.exe"' in text
