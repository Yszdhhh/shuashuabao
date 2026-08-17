"""Tests for LayoutTransform multi-resolution coordinate system (INV-LAYOUT-01)."""

import unittest
from shuabao.layout_transform import (
    BASELINE_WIDTH,
    BASELINE_HEIGHT,
    LayoutTransform,
    SUPPORTED_16_9_RESOLUTIONS,
)


class TestLayoutTransform(unittest.TestCase):
    def test_baseline_identity(self):
        lt = LayoutTransform.from_frame_dimensions(1600, 900)
        self.assertTrue(lt.is_valid())
        self.assertEqual(lt.scale_x, 1.0)
        self.assertEqual(lt.scale_y, 1.0)
        self.assertEqual(lt.logical_point(800, 450), (800, 450))
        self.assertEqual(lt.logical_roi(100, 200, 300, 400), (100, 200, 300, 400))
        self.assertEqual(lt.baseline_point_from_actual(800, 450), (800, 450))

    def test_1080p_scaling(self):
        lt = LayoutTransform.from_frame_dimensions(1920, 1080)
        self.assertTrue(lt.is_valid())
        self.assertAlmostEqual(lt.scale_x, 1.2, places=4)
        self.assertAlmostEqual(lt.scale_y, 1.2, places=4)
        self.assertEqual(lt.logical_point(1000, 500), (1200, 600))
        self.assertEqual(lt.logical_roi(100, 100, 500, 500), (120, 120, 600, 600))

    def test_720p_scaling(self):
        lt = LayoutTransform.from_frame_dimensions(1280, 720)
        self.assertTrue(lt.is_valid())
        self.assertAlmostEqual(lt.scale_x, 0.8, places=4)
        self.assertAlmostEqual(lt.scale_y, 0.8, places=4)
        self.assertEqual(lt.logical_point(1000, 500), (800, 400))
        self.assertEqual(lt.logical_roi(100, 100, 500, 500), (80, 80, 400, 400))

    def test_1440p_scaling(self):
        lt = LayoutTransform.from_frame_dimensions(2560, 1440)
        self.assertTrue(lt.is_valid())
        self.assertAlmostEqual(lt.scale_x, 1.6, places=4)
        self.assertAlmostEqual(lt.scale_y, 1.6, places=4)
        self.assertEqual(lt.logical_point(1000, 500), (1600, 800))
        self.assertEqual(lt.logical_roi(100, 100, 500, 500), (160, 160, 800, 800))

    def test_aspect_ratio_validation(self):
        self.assertTrue(LayoutTransform.is_supported(1600, 900))
        self.assertTrue(LayoutTransform.is_supported(1920, 1080))
        self.assertTrue(LayoutTransform.is_supported(1280, 720))
        self.assertTrue(LayoutTransform.is_supported(2560, 1440))
        self.assertFalse(LayoutTransform.is_supported(1920, 1200))  # 16:10
        self.assertFalse(LayoutTransform.is_supported(1024, 768))   # 4:3
        self.assertFalse(LayoutTransform.is_supported(100, 50))     # Too small
        self.assertFalse(LayoutTransform.is_supported(0, 0))
        self.assertFalse(LayoutTransform.is_supported(None, None))
        self.assertTrue(LayoutTransform.from_frame(1920, 1080).is_valid())
        for w, h in SUPPORTED_16_9_RESOLUTIONS:
            lt = LayoutTransform.from_frame_dimensions(w, h)
            self.assertTrue(lt.is_valid(), f"Resolution {w}x{h} should be supported")

    def test_inv_layout_01_fail_closed_on_unsupported_ratios(self):
        # 16:10 ratio: 1920x1200, 1680x1050, 1440x900
        lt_16_10 = LayoutTransform.from_frame_dimensions(1920, 1200)
        self.assertFalse(lt_16_10.is_valid())

        # 4:3 ratio: 1024x768, 800x600
        lt_4_3 = LayoutTransform.from_frame_dimensions(1024, 768)
        self.assertFalse(lt_4_3.is_valid())

        # 21:9 ultrawide: 3440x1440
        lt_21_9 = LayoutTransform.from_frame_dimensions(3440, 1440)
        self.assertFalse(lt_21_9.is_valid())

        # Very small frame
        lt_tiny = LayoutTransform.from_frame_dimensions(320, 240)
        self.assertFalse(lt_tiny.is_valid())

    def test_normalized_coordinate_mapping(self):
        lt = LayoutTransform.from_frame_dimensions(1920, 1080)
        self.assertEqual(lt.normalized_point_to_actual(0.5, 0.5), (960, 540))
        self.assertEqual(lt.normalized_roi_to_actual(0.1, 0.2, 0.3, 0.4), (192, 216, 576, 432))


if __name__ == "__main__":
    unittest.main()
