"""Unit tests for nomenclature and path migration (GameScript -> ShuaBao / shuabao).

Verifies that primary runtime paths and namespaces use ShuaBao, and that
GameScript paths are isolated strictly for legacy/upstream compatibility.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from shuabao.input.keyboard_mouse import ActionResult, InputExecutor, is_current_process_elevated
from shuabao.settings import (
    LEGACY_UPSTREAM_APPDATA_SETTINGS_PATH,
    OFFICIAL_SETTINGS,
    Settings,
)
from shuabao.vision.capture import LOCAL_HELPER_WINDOW_KEYWORDS, is_local_helper_title
from shuabao.vision.ocr_shadow.worker import _stage_model


class TestNomenclatureMigration(unittest.TestCase):
    """Test suite ensuring ShuaBao runtime paths and namespace migration."""

    def test_settings_legacy_upstream_constant_isolated(self) -> None:
        """Verify legacy official GameScript path is isolated to LEGACY_UPSTREAM constant."""
        self.assertEqual(OFFICIAL_SETTINGS, LEGACY_UPSTREAM_APPDATA_SETTINGS_PATH)
        appdata = os.environ.get("APPDATA", "")
        expected = Path(appdata) / "GameScript" / "Settings" / "Settings.json"
        self.assertEqual(LEGACY_UPSTREAM_APPDATA_SETTINGS_PATH, expected)

    def test_settings_load_official_nonexistent_raises_clear_error(self) -> None:
        """Verify load_official raises FileNotFoundError mentioning legacy upstream."""
        nonexistent = Path("nonexistent_path_test_12345.json")
        with self.assertRaises(FileNotFoundError) as ctx:
            Settings.load_official(nonexistent)
        self.assertIn("legacy upstream official settings not found", str(ctx.exception))

    def test_capture_helper_window_keywords(self) -> None:
        """Verify helper window keywords include ShuaBao, 刷刷宝, and legacy GameScript-Local."""
        self.assertIn("ShuaBao", LOCAL_HELPER_WINDOW_KEYWORDS)
        self.assertIn("刷刷宝", LOCAL_HELPER_WINDOW_KEYWORDS)
        self.assertIn("GameScript-Local", LOCAL_HELPER_WINDOW_KEYWORDS)
        self.assertIn("挂机助手", LOCAL_HELPER_WINDOW_KEYWORDS)
        self.assertIn("本地版", LOCAL_HELPER_WINDOW_KEYWORDS)

        # Confirm helper window filtering behaves properly
        self.assertTrue(is_local_helper_title("ShuaBao - 刷刷宝控制面板"))
        self.assertTrue(is_local_helper_title("刷刷宝 - 挂机助手"))
        self.assertTrue(is_local_helper_title("GameScript-Local Helper"))
        self.assertFalse(is_local_helper_title("GameWindow - KK Platform"))

    def test_ocr_shadow_worker_ascii_stage_prefix(self) -> None:
        """Verify OCR shadow worker uses shuabao_ocr_stage_ prefix."""
        with tempfile.TemporaryDirectory() as src_dir:
            model_dir = Path(src_dir) / "ocr" / "ch_PP-OCRv4_rec_infer"
            model_dir.mkdir(parents=True)
            (model_dir / "inference.pdmodel").write_bytes(b"dummy")
            # Point MODEL_MANIFEST.json next to ocr dir
            manifest = Path(src_dir) / "MODEL_MANIFEST.json"
            manifest.write_text("{}", encoding="utf-8")
            
            # Pass through with a mock or directly testing _stage_model
            import unittest.mock as mock
            with mock.patch("shuabao.vision.ocr_shadow.worker._validate_model", return_value=None):
                dst, reason, stage = _stage_model(model_dir)
                self.assertIsNone(reason)
                self.assertIsNotNone(stage)
                try:
                    stage_name = Path(stage.name).name
                    self.assertTrue(
                        stage_name.startswith("shuabao_ocr_stage_"),
                        f"Expected stage prefix shuabao_ocr_stage_, got {stage_name}",
                    )
                finally:
                    if stage is not None:
                        stage.cleanup()

    def test_keyboard_mouse_elevation_message_uses_shuabao(self) -> None:
        """Verify unelevated execution error message instructs to relaunch ShuaBao."""
        import unittest.mock as mock
        executor = InputExecutor()
        with mock.patch("shuabao.input.keyboard_mouse.is_current_process_elevated", return_value=False):
            res = executor.check_can_execute(dry_run=False)
            self.assertFalse(res.success)
            self.assertEqual(res.status, "CANCELLED_NOT_ELEVATED")
            self.assertIn("Relaunch ShuaBao", res.message)
            self.assertIn("KK/ShuaBao", res.message)

if __name__ == "__main__":
    unittest.main()
