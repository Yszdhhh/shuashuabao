"""PrintWindow(ImageGrab) 位图尺寸自证测试。

背景：ImageGrab.grab(window=...) 抓到的位图尺寸可能与目标 client 尺寸
不一致（DPI 缩放/窗口边框差异）。此前只打印诊断仍返回 is_valid=True 帧，
下游模板匹配会拿错坐标的位图当有效证据。
要求：尺寸不一致 → is_valid=False Frame + 诊断 error，禁止裁剪/拉伸/伪装；
client 尺寸未知时回退到窗口尺寸，但回退后仍必须匹配。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.vision.capture import WindowTarget, _capture_print_window  # noqa: E402


def _bitmap(w: int, h: int) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[10:20, 10:20] = 255
    return img


class CaptureSizeSelfCheckTests(unittest.TestCase):
    def _target(self, client_w=800, client_h=600, window_w=820, window_h=620):
        return WindowTarget(
            hwnd=42,
            title="kk",
            left=100,
            top=50,
            width=window_w,
            height=window_h,
            client_left=110,
            client_top=60,
            client_width=client_w,
            client_height=client_h,
        )

    def test_matching_client_size_is_valid(self):
        with patch("PIL.ImageGrab.grab", return_value=_bitmap(800, 600)):
            frame = _capture_print_window(self._target(800, 600))
        self.assertIsNotNone(frame)
        self.assertTrue(frame.is_valid)
        self.assertIsNone(frame.error)
        self.assertEqual((800, 600), (frame.width, frame.height))

    def test_mismatched_client_size_is_invalid_with_diagnostic(self):
        with patch("PIL.ImageGrab.grab", return_value=_bitmap(780, 590)):
            frame = _capture_print_window(self._target(800, 600))
        self.assertIsNotNone(frame)
        self.assertFalse(frame.is_valid, "位图尺寸与 client 不一致时必须是无效帧")
        self.assertIsNotNone(frame.error, "必须带诊断 error")
        self.assertIn("780", frame.error)
        self.assertIn("800", frame.error)

    def test_unknown_client_size_falls_back_to_window_and_matches(self):
        target = self._target(client_w=0, client_h=0, window_w=800, window_h=600)
        with patch("PIL.ImageGrab.grab", return_value=_bitmap(800, 600)):
            frame = _capture_print_window(target)
        self.assertTrue(frame.is_valid)
        self.assertEqual((800, 600), (frame.width, frame.height))

    def test_unknown_client_size_fallback_mismatch_is_invalid(self):
        target = self._target(client_w=0, client_h=0, window_w=800, window_h=600)
        with patch("PIL.ImageGrab.grab", return_value=_bitmap(780, 590)):
            frame = _capture_print_window(target)
        self.assertFalse(frame.is_valid, "回退到窗口尺寸后不匹配也必须无效")
        self.assertIn("780", frame.error)

    def test_no_crop_no_stretch_no_fake_dimensions(self):
        # 位图原样判定：既不裁剪也不拉伸；无效帧不得携带被调过的伪尺寸
        with patch("PIL.ImageGrab.grab", return_value=_bitmap(800, 700)):
            frame = _capture_print_window(self._target(800, 600))
        self.assertFalse(frame.is_valid)
        self.assertEqual((0, 0), (frame.width, frame.height), "无效帧应使用空位图而不是伪装尺寸")


if __name__ == "__main__":
    unittest.main()
