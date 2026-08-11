from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import gamescript.vision.matcher as matcher_mod
from gamescript.vision.capture import Frame
from gamescript.vision.matcher import (
    MatchSearch,
    _load_template,
    find_blue_buttons,
    match_any,
    match_any_with_margin,
    match_one,
    match_scenes,
    preferred_scales,
)


ROOT = Path(__file__).resolve().parents[1]
SCALES = (0.9, 1.0, 1.1, 1.15, 1.2)
_IMAGES = ROOT / "assets" / "Images"


def _scaled_fixture(name: str, scale: float = 1.15) -> Frame:
    path = _IMAGES / f"{name}.png"
    template = _load_template(path)
    assert template is not None
    scaled = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    frame = np.zeros((max(320, scaled.shape[0] + 80), max(480, scaled.shape[1] + 120), 3), dtype=np.uint8)
    y, x = 40, 60
    frame[y:y + scaled.shape[0], x:x + scaled.shape[1]] = scaled
    return Frame(frame)


class MultiScaleMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = _IMAGES

    def test_start_button_survives_window_scaling(self):
        hit = match_any(_scaled_fixture("startGameBtn"), self.images, ["startGameBtn"], scales=SCALES)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score, 0.95)

    def test_stage_marker_survives_window_scaling(self):
        hit = match_any(_scaled_fixture("stage"), self.images, ["stage"], scales=SCALES)
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.score, 0.95)


class EarlyStopTests(unittest.TestCase):
    """N2.1：优先级早停、margin 语义、主/邻尺度、ROI-first 蓝色按钮、场景级 match_scenes。"""

    @classmethod
    def setUpClass(cls):
        cls.images = ROOT / "assets" / "Images"

    def _two_hit_frame(self) -> Frame:
        """startGameBtn（加噪 20%，分数≈0.8x）与 stage（原样，分数≈1.0）同帧。"""
        h1, w1 = _load_template(self.images / "startGameBtn.png").shape[:2]
        h2, w2 = _load_template(self.images / "stage.png").shape[:2]
        frame = np.zeros((max(h1, h2) + 80, w1 + w2 + 240, 3), dtype=np.uint8)
        self._paste(frame, self.images, "startGameBtn", 60, 40, noise=0.20)
        self._paste(frame, self.images, "stage", 60 + w1 + 120, 40)
        return Frame(frame)

    @staticmethod
    def _paste(frame: np.ndarray, images: Path, name: str, x: int, y: int, noise: float = 0.0) -> None:
        template = _load_template(images / f"{name}.png")
        h, w = template.shape[:2]
        patch_img = template.copy()
        if noise > 0.0:
            rng = np.random.default_rng(42)
            mask = rng.random((h, w)) < noise
            patch_img[mask] = rng.integers(0, 256, size=(int(mask.sum()), 3), dtype=np.uint8)
        frame[y:y + h, x:x + w] = patch_img

    def test_early_stop_returns_first_configured_threshold_hit_and_marks_partial_margin(self):
        frame = self._two_hit_frame()
        with patch.object(matcher_mod.cv2, "matchTemplate", wraps=matcher_mod.cv2.matchTemplate) as mt:
            res = match_any_with_margin(
                frame, self.images, ["startGameBtn", "stage"],
                threshold=0.80, scales=(1.0,), early_stop=True,
            )
        self.assertIsNotNone(res.best)
        self.assertEqual(res.best.name, "startGameBtn", "early_stop 必须按配置顺序返回第一个过阈值命中")
        self.assertFalse(res.compared_all, "提前停止必须标记局部比较")
        self.assertIsNone(res.second_best)
        self.assertEqual(mt.call_count, 1, "early_stop 命中后不得扫描后续 names")

        # 对照：全扫描取全局最高分（stage 分数更高）
        full = match_any_with_margin(frame, self.images, ["startGameBtn", "stage"], threshold=0.80, scales=(1.0,))
        self.assertTrue(full.compared_all)
        self.assertEqual(full.best.name, "stage")
        self.assertIsNotNone(full.second_best)
        self.assertGreaterEqual(full.margin, 0.0)

    def test_margin_request_disables_early_stop_and_keeps_second_best(self):
        frame = self._two_hit_frame()
        # min_margin>0 → 禁止早停，自动全扫描，保留完整 margin 语义
        res = match_any_with_margin(
            frame, self.images, ["startGameBtn", "stage"],
            threshold=0.80, scales=(1.0,), min_margin=0.10, early_stop=True,
        )
        self.assertTrue(res.compared_all, "min_margin>0 必须自动转全扫描")
        self.assertEqual(res.best.name, "stage")
        self.assertIsNotNone(res.second_best)
        self.assertGreaterEqual(res.margin, 0.10)
        # margin 不足 → 拒绝
        res2 = match_any_with_margin(
            frame, self.images, ["startGameBtn", "stage"],
            threshold=0.80, scales=(1.0,), min_margin=0.95, early_stop=True,
        )
        self.assertIsNone(res2.best)
        self.assertIsNotNone(res2.second_best)

    def test_primary_scale_hit_skips_neighbor_and_later_scales(self):
        template_path = self.images / "startGameBtn.png"
        frame = _scaled_fixture("startGameBtn", scale=1.0)
        with patch.object(matcher_mod.cv2, "matchTemplate", wraps=matcher_mod.cv2.matchTemplate) as mt:
            hit = match_one(frame, template_path, threshold=0.85, scales=(1.0, 1.06, 1.12), early_stop_scale=True)
        self.assertIsNotNone(hit)
        self.assertEqual(mt.call_count, 1, "主尺度命中后不得再试邻域/后续尺度")

        # 对照：无 early_stop_scale 时全 scales 扫描
        with patch.object(matcher_mod.cv2, "matchTemplate", wraps=matcher_mod.cv2.matchTemplate) as mt2:
            match_one(frame, template_path, threshold=0.85, scales=(1.0, 1.06, 1.12))
        self.assertEqual(mt2.call_count, 3)

    def test_primary_scale_miss_tries_exactly_one_neighbor(self):
        template_path = self.images / "startGameBtn.png"
        # 模板按 1.06 缩放粘贴：主尺度 1.0 miss，邻域 1.06 命中
        frame = _scaled_fixture("startGameBtn", scale=1.06)
        with patch.object(matcher_mod.cv2, "matchTemplate", wraps=matcher_mod.cv2.matchTemplate) as mt:
            hit = match_one(frame, template_path, threshold=0.85, scales=(1.0, 1.06, 1.12), early_stop_scale=True)
        self.assertIsNotNone(hit)
        self.assertEqual(mt.call_count, 2, "主尺度 miss 后最多尝试一个邻域")

        # 邻域也 miss：恰好一个邻域后停止，不试更远尺度
        frame2 = _scaled_fixture("startGameBtn", scale=1.20)
        with patch.object(matcher_mod.cv2, "matchTemplate", wraps=matcher_mod.cv2.matchTemplate) as mt2:
            hit2 = match_one(frame2, template_path, threshold=0.85, scales=(1.0, 1.06), early_stop_scale=True)
        self.assertIsNone(hit2)
        self.assertEqual(mt2.call_count, 2)

    def test_preferred_scales_dedup_sorts_and_clamps(self):
        self.assertEqual(preferred_scales(1.0), (1.0, 1.06))
        self.assertEqual(preferred_scales(0.6), (0.6, 0.636))
        self.assertEqual(preferred_scales(1.0, 1.0), (1.0,))
        self.assertEqual(preferred_scales(1.15, 1.2), (1.15, 1.2))
        # 主尺度保持调用方意图；邻域夹在 [min(0.85, primary), max(1.2, primary)]
        self.assertEqual(preferred_scales(1.3), (1.3,))

    def test_find_blue_buttons_converts_only_roi_and_returns_global_coordinates(self):
        frame = np.zeros((300, 500, 3), dtype=np.uint8)
        # ROI (0.2,0.2,0.5,0.5) → x∈[100,250] y∈[60,150]：只含第一个矩形
        cv2.rectangle(frame, (100, 60), (240, 110), (255, 0, 0), -1)   # 140x50 蓝色
        cv2.rectangle(frame, (300, 200), (410, 250), (255, 0, 0), -1)  # 110x50 ROI 外
        fr = Frame(frame)
        shapes: list[tuple[int, int]] = []
        orig_cvt = matcher_mod.cv2.cvtColor

        def spy(src, *a, **k):
            shapes.append(src.shape[:2])
            return orig_cvt(src, *a, **k)

        with patch.object(matcher_mod.cv2, "cvtColor", side_effect=spy):
            hits = find_blue_buttons(fr, roi=(0.2, 0.2, 0.5, 0.5))
        self.assertEqual(shapes, [(90, 150)], "必须只对 ROI 区域做 cvtColor/HSV")
        self.assertEqual(len(hits), 1, "ROI 外候选不得出现")
        self.assertEqual((hits[0].x, hits[0].y), (100, 60), "contour 坐标必须回映到原帧")
        # roi=None → 全图
        with patch.object(matcher_mod.cv2, "cvtColor", side_effect=spy):
            hits_all = find_blue_buttons(fr)
        self.assertEqual(shapes[-1], (300, 500))
        self.assertEqual(len(hits_all), 2)
        # 空/退化 ROI → []
        self.assertEqual(find_blue_buttons(fr, roi=(0.5, 0.5, 0.4, 0.9)), [])

    def test_match_scenes_respects_scene_priority_and_scene_specific_roi(self):
        h1, w1 = _load_template(self.images / "startGameBtn.png").shape[:2]
        h2, w2 = _load_template(self.images / "stage.png").shape[:2]
        frame = np.zeros((max(h1, h2) + 80, w1 + w2 + 240, 3), dtype=np.uint8)
        self._paste(frame, self.images, "startGameBtn", 60, 40)
        self._paste(frame, self.images, "stage", 60 + w1 + 120, 40)
        fr = Frame(frame)
        searches = [
            ("alpha", MatchSearch(names=("startGameBtn",), threshold=0.85, roi=(0.0, 0.0, 0.35, 0.6))),
            ("beta", MatchSearch(names=("stage",), threshold=0.85, roi=(0.35, 0.0, 1.0, 0.6))),
        ]
        key, hit = match_scenes(fr, self.images, searches)
        self.assertEqual(key, "alpha", "场景必须按优先级顺序，命中即停")
        self.assertEqual(hit.name, "startGameBtn")
        # 场景级 ROI：把 stage 移到 beta 的 ROI 之外 → beta miss，alpha 命中
        frame2 = np.zeros((max(h1, h2) + 420, w1 + w2 + 240, 3), dtype=np.uint8)
        self._paste(frame2, self.images, "startGameBtn", 60, 250)  # 下区：仅在 alpha ROI
        self._paste(frame2, self.images, "stage", 60, 300)         # 更下：beta/alpha ROI 之外
        fr2 = Frame(frame2)
        searches2 = [
            ("beta", MatchSearch(names=("stage",), threshold=0.85, roi=(0.0, 0.0, 0.9, 0.45))),
            ("alpha", MatchSearch(names=("startGameBtn",), threshold=0.85, roi=(0.0, 0.45, 0.5, 1.0))),
        ]
        key2, hit2 = match_scenes(fr2, self.images, searches2)
        self.assertEqual(key2, "alpha", "scene 专属 ROI 必须生效")


class N24GrayTests(unittest.TestCase):
    """N2.4：灰度候选 + 局部彩色复核 + hue 彩色路径 + 模板灰度缓存。"""

    @classmethod
    def setUpClass(cls):
        cls.images = _IMAGES

    def setUp(self):
        matcher_mod.clear_template_cache()

    def _paste(self, frame, name, x, y):
        tpl = _load_template(self.images / f"{name}.png")
        frame[y : y + tpl.shape[0], x : x + tpl.shape[1]] = tpl

    def test_gray_first_returns_color_verified_hit(self):
        """形状/文字类模板：灰度候选命中且局部彩色复核通过 → 返回彩色分数命中。"""
        tpl = _load_template(self.images / "startGameBtn.png")
        frame = np.zeros((max(320, tpl.shape[0] + 80), max(480, tpl.shape[1] + 120), 3), dtype=np.uint8)
        x, y = 60, 40
        frame[y : y + tpl.shape[0], x : x + tpl.shape[1]] = tpl
        fr = Frame(frame)
        hit = match_one(fr, self.images / "startGameBtn.png", threshold=0.85, name="startGameBtn")
        self.assertIsNotNone(hit, "灰度候选 + 彩色复核必须命中真实粘贴的模板")
        self.assertGreaterEqual(hit.score, 0.85, "返回的分数是彩色复核分数（原彩色刻度）")
        self.assertLessEqual(abs(hit.x - x), 1)
        self.assertLessEqual(abs(hit.y - y), 1)

    def test_gray_hit_rejected_by_color_recheck_is_miss(self):
        """灰度峰通过但局部彩色复核不过 → 视为假阳性，不产出结果。"""
        tpl = _load_template(self.images / "startGameBtn.png")
        frame = np.zeros((max(320, tpl.shape[0] + 80), max(480, tpl.shape[1] + 120), 3), dtype=np.uint8)
        x, y = 60, 40
        frame[y : y + tpl.shape[0], x : x + tpl.shape[1]] = tpl
        fr = Frame(frame)
        with patch.object(matcher_mod, "_color_verify", return_value=(False, 0.1)) as cv:
            hit = match_one(fr, self.images / "startGameBtn.png", threshold=0.85, name="startGameBtn")
        cv.assert_called()
        self.assertIsNone(hit, "彩色复核否决的灰度命中必须作为 miss（假阳性过滤）")

    def test_hue_templates_stay_on_color_path(self):
        """龙珠卡蓝框等 hue 模板保持彩色：matchTemplate 的输入必须是 3 通道 BGR。"""
        seen: list[int] = []
        orig_match = matcher_mod.cv2.matchTemplate

        def spy(image, templ, method, *a, **k):
            seen.append(image.ndim)
            return orig_match(image, templ, method, *a, **k)

        tpl = _load_template(self.images / "longzhu.png")
        frame = np.zeros((max(320, tpl.shape[0] + 80), max(480, tpl.shape[1] + 120), 3), dtype=np.uint8)
        frame[40 : 40 + tpl.shape[0], 60 : 60 + tpl.shape[1]] = tpl
        fr = Frame(frame)
        with patch.object(matcher_mod.cv2, "matchTemplate", side_effect=spy):
            hit = match_one(fr, self.images / "longzhu.png", threshold=0.85, name="longzhu")
        self.assertTrue(all(nd == 3 for nd in seen), "hue 模板必须走彩色路径")
        self.assertIsNotNone(hit, "龙珠卡在彩色路径下必须命中")

    def test_gray_template_converted_once_per_path(self):
        """灰度模板在加载时一次转换并缓存（同路径不重复 cvtColor）。"""
        tpl = _load_template(self.images / "startGameBtn.png")
        frame = np.zeros((max(320, tpl.shape[0] + 80), max(480, tpl.shape[1] + 120), 3), dtype=np.uint8)
        frame[40 : 40 + tpl.shape[0], 60 : 60 + tpl.shape[1]] = tpl
        fr = Frame(frame)
        path = self.images / "startGameBtn.png"
        orig_cvt = matcher_mod.cv2.cvtColor

        def spy(src, *a, **k):
            if a and a[0] == getattr(matcher_mod.cv2, "COLOR_BGR2GRAY"):
                gray_calls.append(src.shape)
            return orig_cvt(src, *a, **k)

        gray_calls: list = []
        with patch.object(matcher_mod.cv2, "cvtColor", side_effect=spy):
            match_one(fr, path, threshold=0.85, name="a", scales=(1.0,))
            match_one(fr, path, threshold=0.85, name="b", scales=(1.0,))
        tpl_gray = [s for s in gray_calls if s == (tpl.shape[0], tpl.shape[1], 3)]
        self.assertEqual(tpl_gray, [(tpl.shape[0], tpl.shape[1], 3)], "模板灰度必须只转换一次")

    def test_content_dedup_skips_identical_template_files(self):
        """同图多名（字节相同）只扫描一次：kk_start/lobby/room_start 内容相同。"""
        tpl = _load_template(self.images / "kk_start.png")
        frame = np.zeros((max(320, tpl.shape[0] + 80), max(480, tpl.shape[1] + 120), 3), dtype=np.uint8)
        frame[40 : 40 + tpl.shape[0], 60 : 60 + tpl.shape[1]] = tpl
        fr = Frame(frame)
        names = ["kk_start", "lobby/room_start", "lobby/room_start_alt", "lobby/startGameBtn"]
        orig_match = matcher_mod.cv2.matchTemplate
        calls = []
        with patch.object(matcher_mod.cv2, "matchTemplate", side_effect=lambda *a, **k: (calls.append(1), orig_match(*a, **k))[1]):
            res = match_any_with_margin(fr, self.images, names, threshold=0.85, scales=(1.0,), early_stop=True)
        self.assertEqual(len(calls), 1, "字节相同的 4 个名字必须去重为 1 次扫描")
        self.assertIsNotNone(res.best)


if __name__ == "__main__":
    unittest.main()
