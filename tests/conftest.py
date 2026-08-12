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


def pytest_collection_modifyitems(config, items):  # noqa: ANN001
    """云端 Linux 缺 OCR 权重 / 官方 raw 素材 / windll 时跳过对应用例。

    Windows 本机完整素材下这些 skip 不会触发；不改行为基线快照。
    """
    import pytest

    skip_ocr = pytest.mark.skip(reason="OCR model weights absent (models/ocr/*_infer)")
    skip_win = pytest.mark.skip(reason="requires ctypes.windll (Windows)")
    skip_raw = pytest.mark.skip(reason="official_raw / runtime_sample fixtures absent")

    ocr_weights = ROOT / "models" / "ocr" / "PP-OCRv5_mobile_rec_infer" / "inference.json"
    has_ocr = ocr_weights.is_file()
    has_windll = hasattr(__import__("ctypes"), "windll")
    has_official_raw = (ROOT / "docs" / "agent_shared_logs" / "official_raw").is_dir()
    has_runtime_sample = (ROOT / "docs" / "runtime_sample" / "live_l0_0_857518.png").is_file()

    for item in items:
        node = item.nodeid
        if not has_ocr and (
            "test_ocr_eval.py::TestModelManifest::test_mobile_entry_records_real_hashes" in node
            or "test_ocr_eval.py::TestHashGate::" in node
            or "test_ocr_eval.py::TestNegativeChain::" in node
        ):
            item.add_marker(skip_ocr)
        if not has_windll and (
            "test_get_window_class_name_mock" in node
            or "test_get_window_process_info_mock" in node
            or "test_paste_text_preserves_clipboard" in node
        ):
            item.add_marker(skip_win)
        if (not has_official_raw and "test_in_game_stage_glyph_is_negative" in node) or (
            not has_runtime_sample and (
                "test_low_margin_rejects_candidate_action" in node
                or "test_replay_fixtures_and_negative_samples" in node
            )
        ):
            item.add_marker(skip_raw)
