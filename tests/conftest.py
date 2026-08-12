"""让 tests/ 下每个文件都能独立运行。

此前只有部分测试文件自己 `sys.path.insert(ROOT/"src")`，其余（如
tests/test_choice_policy.py）依赖同一次 pytest 会话里字母序更靠前的文件先插入
路径。整目录跑没问题，但单独跑某个文件会 ModuleNotFoundError: gamescript，
调试单个用例时很容易被误判成代码坏了。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def _install_linux_win_shims() -> None:
    """Allow Windows-oriented input helpers to import on Linux for unit tests."""
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

# Lobby UIA backend imports Windows-only ctypes.HRESULT at module import time.
# Keep the suite collectable on Linux cloud/CI; these files still run on win32.
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
    """Skip tests that need gitignored/local-only assets on this host.

    Cloud Linux agents do not ship OCR model binaries (gitignore) or
    docs/agent_shared_logs/official_raw/. Skipping keeps the gate honest
    instead of collection/runtime ERROR that would zero out the suite.
    """
    import pytest

    ocr_model = ROOT / "models" / "ocr" / "PP-OCRv5_mobile_rec_infer" / "inference.json"
    official_raw = ROOT / "docs" / "agent_shared_logs" / "official_raw"
    lobby_shot = official_raw / "20260803_CaptureWindow_20260803154629.png"

    skip_ocr = pytest.mark.skip(reason="OCR model binaries not present (models/ocr gitignored)")
    skip_raw = pytest.mark.skip(reason="official_raw captures gitignored / not on this host")

    for item in items:
        node = item.nodeid
        if not ocr_model.is_file():
            if "::TestModelManifest::test_mobile_entry_records_real_hashes" in node:
                item.add_marker(skip_ocr)
            if "::TestHashGate::" in node:
                item.add_marker(skip_ocr)
            if "::TestNegativeChain::" in node:
                item.add_marker(skip_ocr)
        if not official_raw.is_dir() or not lobby_shot.is_file():
            if "test_in_game_stage_glyph_is_negative_and_real_stage_fixture_passes" in node:
                item.add_marker(skip_raw)
            if node.startswith("tests/test_p0b_replay.py::"):
                item.add_marker(skip_raw)
            if node.startswith("tests/test_p0b1_fixes.py::") and "stage_glyph" in node:
                item.add_marker(skip_raw)
