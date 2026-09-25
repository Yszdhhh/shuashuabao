"""让 tests/ 下每个文件都能独立运行，并在缺本地资产的主机上诚实跳过。

路径注入：此前只有部分测试文件自己 `sys.path.insert(ROOT/"src")`，其余（如
tests/test_choice_policy.py）依赖同一次 pytest 会话里字母序更靠前的文件先插入
路径。整目录跑没问题，但单独跑某个文件会 ModuleNotFoundError: shuabao，
调试单个用例时很容易被误判成代码坏了。

跳过策略（A/B 两组云端 agent 合并而来）：OCR 模型二进制、`official_raw` 实机
截图都是 gitignore 的本地资产，Linux 云端拿不到；UIA 后端在 import 期就要
Windows-only 的 `ctypes.HRESULT`。与其让它们 ERROR 把整套结果清零，不如显式
skip 并在门禁快照里记明。

**Windows 满资产主机上这些 skip 一条都不会触发**——所以门禁基线必须在
Windows 上重跑确定，不能沿用云端的通过数（云端会少 40+ 条）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

# 离线 tests/ 和 release gate 绝不能继承操作员桌面上的 live 订阅环境。
# 用户可以在 Windows 用户环境中设置 enforce/远端 endpoint；若不隔离，
# 与订阅无关的 facade/面板测试会突然尝试真实授权并统一报 PERMIT_MISSING。
# 需要覆盖该边界的用例必须用 pytest monkeypatch 显式设置，而不是依赖宿主机。
_LIVE_SUBSCRIPTION_ENV = (
    "SHUABAO_SUBSCRIPTION_MODE",
    "SHUABAO_SUBSCRIPTION_BASE_URL",
    "SHUABAO_SUBSCRIPTION_LICENSE_KEY",
    "SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT",
    "SHUABAO_SUBSCRIPTION_TIMEOUT_S",
)
for _name in _LIVE_SUBSCRIPTION_ENV:
    os.environ.pop(_name, None)

# B6：pytest 曾经把打印写进真实的 %LOCALAPPDATA%\ShuaBao\logs\ShuaBao.log ——
# shuabao.shell.main_window 在模块加载时用 get_canonical_app_data_dir() 给
# 共享的 "ShuaBao" logger 挂一个真实 RotatingFileHandler（GameScript-Local
# AGENTS.md 记录的 1970 时间戳污染即此：某些用例 patch("time.time", ...) 把
# 全局时钟冻结到极小 epoch，日志的 asctime 随之写出 1970 年时间戳）。
# 必须在任何 shuabao.* 模块被导入前把 SHUABAO_APP_DATA 重定向到临时目录，
# 让 get_canonical_app_data_dir()（及沿用它的 main_window.APP_DATA）全部落在
# tmp 里，不再触碰宿主机上的真实 AppData 日志/设置/锁文件。
import tempfile as _tempfile

_tmp_appdata = Path(_tempfile.mkdtemp(prefix="shuabao-pytest-appdata-")) / "ShuaBao"
_tmp_appdata.mkdir(parents=True, exist_ok=True)
os.environ["SHUABAO_APP_DATA"] = str(_tmp_appdata)

if not os.environ.get("SHUABAO_OCR_PYTHON"):
    for _candidate in (
        ROOT.parent.parent / "GameScript-Local" / ".venv-ocr" / "Scripts" / "python.exe",
        ROOT.parent / "live-solo-cc17962" / ".venv-ocr" / "Scripts" / "python.exe",
    ):
        if _candidate.is_file():
            os.environ["SHUABAO_OCR_PYTHON"] = str(_candidate)
            break

if not os.environ.get("SHUABAO_OCR_MODEL_DIR"):
    for _candidate in (
        ROOT.parent.parent / "GameScript-Local" / "models" / "ocr",
        ROOT.parent / "live-solo-cc17962" / "models" / "ocr",
    ):
        if _candidate.is_dir():
            os.environ["SHUABAO_OCR_MODEL_DIR"] = str(_candidate)
            break



def _install_linux_win_shims() -> None:
    """让面向 Windows 的输入模块能在 Linux 上被导入（仅为单测收集，不改行为）。"""
    if sys.platform == "win32":
        return
    import ctypes
    import types

    if not hasattr(ctypes, "windll"):
        class _AttrDll:
            def __getattr__(self, name: str):  # noqa: ANN001
                def _missing(*_a, **_k):  # noqa: ANN001
                    raise OSError(f"ctypes.windll stub has no {name}")

                return _missing

        ctypes.windll = types.SimpleNamespace(user32=_AttrDll(), kernel32=_AttrDll())
    if "ctypes.wintypes" not in sys.modules:
        sys.modules["ctypes.wintypes"] = types.ModuleType("ctypes.wintypes")


_install_linux_win_shims()

# UIA 后端 import 期就依赖 Windows-only 的 ctypes.HRESULT；Linux 上整文件跳过收集。
collect_ignore: list[str] = []
if sys.platform != "win32":
    collect_ignore.extend(
        [
            "test_uia_adapter.py",
            "test_uia_selector.py",
            "test_uia_tree.py",
        ]
    )


def pytest_collection_modifyitems(config, items):  # noqa: ANN001
    """按本机实际拥有的资产跳过对应用例（Windows 满资产时不触发任何 skip）。"""
    import pytest

    ocr_model = ROOT / "models" / "ocr" / "PP-OCRv5_mobile_rec_infer" / "inference.json"
    official_raw = ROOT / "docs" / "agent_shared_logs" / "official_raw"
    lobby_shot = official_raw / "20260803_CaptureWindow_20260803154629.png"
    runtime_sample = ROOT / "docs" / "runtime_sample" / "live_l0_0_857518.png"

    has_ocr = ocr_model.is_file()
    has_windll = hasattr(__import__("ctypes"), "windll")
    has_official_raw = official_raw.is_dir() and lobby_shot.is_file()
    has_runtime_sample = runtime_sample.is_file()

    skip_ocr = pytest.mark.skip(reason="OCR model binaries not present (models/ocr gitignored)")
    skip_win = pytest.mark.skip(reason="requires ctypes.windll (Windows)")
    skip_raw = pytest.mark.skip(reason="official_raw / runtime_sample captures not on this host")

    for item in items:
        node = item.nodeid

        if not has_ocr and (
            "::TestModelManifest::test_mobile_entry_records_real_hashes" in node
            or "::TestHashGate::" in node
            or "::TestNegativeChain::" in node
        ):
            item.add_marker(skip_ocr)

        if not has_windll and (
            "test_get_window_class_name_mock" in node
            or "test_get_window_process_info_mock" in node
            or "test_paste_text_preserves_clipboard" in node
        ):
            item.add_marker(skip_win)

        if not has_official_raw and (
            "test_in_game_stage_glyph_is_negative" in node
            or node.startswith("tests/test_p0b_replay.py::")
            or (node.startswith("tests/test_p0b1_fixes.py::") and "stage_glyph" in node)
        ):
            item.add_marker(skip_raw)

        if not has_runtime_sample and (
            "test_low_margin_rejects_candidate_action" in node
            or "test_replay_fixtures_and_negative_samples" in node
        ):
            item.add_marker(skip_raw)


def _prime_ocr_worker() -> None:
    """Warm the real OCR worker once per session when this host has one.

    The per-request budget is 1.5s.  On a cold disk cache the first inference
    of a freshly spawned worker can overrun it: the request times out, the
    worker is killed and a live-OCR assertion fails on the first gate run only
    (local 2026-09-24: 1 failure on the first run, 2680 passed on the rerun).
    Priming loads the model files into the OS cache before any test runs.
    """
    try:
        from shuabao.vision.ocr_shadow.production import ProductionShadowClient

        client = ProductionShadowClient(repo_root=ROOT)
    except Exception:
        return  # no OCR runtime on this host (cloud/Linux): nothing to prime
    try:
        if client.start():
            client.warmup(timeout_ms=60000)
    except Exception:
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass


def pytest_sessionstart(session):  # noqa: ANN001
    if os.environ.get("SHUABAO_SKIP_OCR_PRIME") != "1":
        _prime_ocr_worker()

