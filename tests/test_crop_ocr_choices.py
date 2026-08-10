"""O1 裁剪器（tools/crop_ocr_choices.py）定向测试。

覆盖：
- per_slot 显式 bbox 紧裁：name/progress 分别按 slot.roi 裁剪并记录像素框；
- 无显式 bbox 的槽位 → layout_status=unverified_layout、不裁剪（禁止静默全局 fallback）；
- manifest 记录每槽 生效 bbox/来源帧/分辨率/session/truth 规范名；
- truth 别名纠正（奥术激光→奥数激光）与词典外标 unknown；
- contact sheet 生成（图片集合 + 索引）。

运行：.venv\\Scripts\\python.exe -m unittest tests.test_crop_ocr_choices -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import crop_ocr_choices as crp  # noqa: E402


def _make_frame(tmp: Path, w: int = 1600, h: int = 900) -> Path:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), (40, 40, 60))
    d = ImageDraw.Draw(img)
    # 在预期 bbox 处画"文字"色块，便于断言裁剪内容
    d.rectangle([624, 166, 720, 212], fill=(240, 240, 240))
    d.rectangle([700, 330, 780, 360], fill=(255, 200, 0))
    p = tmp / "frame_gt.png"
    img.save(p)
    return p


class TestRoiBoxes(unittest.TestCase):
    def test_per_slot_explicit_bbox(self):
        entry = {"roi_mode": "per_slot"}
        slot = {"index": 0, "roi": {"name": [0.3900, 0.1844, 0.4500, 0.2356],
                                    "progress": [0.4375, 0.3667, 0.4875, 0.4000]}}
        out = crp.roi_boxes_for_slot(entry, slot, 1600, 900)
        self.assertEqual(out["status"], "verified")
        self.assertEqual(out["name"], (0.39, 0.1844, 0.45, 0.2356))
        self.assertEqual(out["progress"], (0.4375, 0.3667, 0.4875, 0.4))

    def test_missing_roi_is_unverified_no_fallback(self):
        # O1：未知布局禁止静默全局 fallback
        entry = {"roi_mode": "per_slot"}
        slot = {"index": 1, "roi": {}}
        out = crp.roi_boxes_for_slot(entry, slot, 1600, 900)
        self.assertEqual(out["status"], "unverified_layout")
        self.assertIsNone(out["name"])
        self.assertIsNone(out["progress"])

    def test_progress_false_means_no_progress_crop(self):
        entry = {"roi_mode": "per_slot"}
        slot = {"index": 0, "roi": {"name": [0.39, 0.1844, 0.45, 0.2356], "progress": False}}
        out = crp.roi_boxes_for_slot(entry, slot, 1600, 900)
        self.assertEqual(out["status"], "verified")
        self.assertIsNone(out["progress"])

    def test_invalid_roi_tuple_rejected(self):
        entry = {"roi_mode": "per_slot"}
        slot = {"index": 0, "roi": {"name": [0.5, 0.5, 0.2, 0.2]}}
        out = crp.roi_boxes_for_slot(entry, slot, 1600, 900)
        self.assertEqual(out["status"], "unverified_layout")


class TestProcessEntry(unittest.TestCase):
    def _entry(self, tmp: Path) -> dict:
        frame = _make_frame(tmp)
        return {
            "id": "test_panel_1",
            "frame": str(frame),
            "kind": "skill",
            "session_id": "test_sess",
            "source": "unit_test",
            "game_version": "test",
            "roi_mode": "per_slot",
            "slots": [
                {
                    "index": 0,
                    "canonical_name": "光法",
                    "raw_text": "光法",
                    "rarity": None,
                    "set_progress": None,
                    "is_valid": True,
                    "is_dragon_ball": False,
                    "roi": {"name": [0.3900, 0.1844, 0.4500, 0.2356], "progress": False},
                },
                {
                    "index": 1,
                    "canonical_name": "奥术激光",
                    "raw_text": "奥术激光",
                    "rarity": None,
                    "set_progress": None,
                    "is_valid": True,
                    "is_dragon_ball": False,
                    "roi": {"name": [0.4375, 0.1844, 0.4975, 0.2356], "progress": False},
                },
                {
                    "index": 2,
                    "canonical_name": "完全不在词典的虚构名",
                    "raw_text": "完全不在词典的虚构名",
                    "rarity": None,
                    "set_progress": None,
                    "is_valid": True,
                    "is_dragon_ball": False,
                    # 无 roi → unverified_layout
                },
            ],
        }

    def test_process_entry_records_bbox_truth_layout(self):
        lexicon = crp.load_lexicon()
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            out = tmp / "fixtures"
            violations: list = []
            copies: list = []
            m = crp.process_entry(self._entry(tmp), out, violations, copies, lexicon)
            self.assertIsNotNone(m)
            self.assertEqual(m["window_size"], [1600, 900])
            self.assertEqual(m["session_id"], "test_sess")
            self.assertIn("frames/test_sess/frame_gt.png", m["original_frame"])
            slots = m["slots"]
            # slot0: 紧裁 name，无 progress crop
            self.assertEqual(slots[0]["layout_status"], "verified")
            self.assertEqual(slots[0]["truth_status"], "in_lexicon")
            self.assertEqual(slots[0]["canonical_name"], "光法")
            self.assertIsNotNone(slots[0]["roi"]["name"])
            self.assertIsNone(slots[0]["roi"]["progress"])
            self.assertEqual(slots[0]["roi_px"]["name"]["pixels"], [624, 166, 720, 212])
            # slot1: 别名纠正 奥术激光 → 奥数激光
            self.assertEqual(slots[1]["truth_status"], "alias_covered")
            self.assertEqual(slots[1]["canonical_name"], "奥数激光")
            self.assertEqual(slots[1]["canonical_corrected_from"], "奥术激光")
            # slot2: 无 bbox → unverified_layout + unknown truth
            self.assertEqual(slots[2]["layout_status"], "unverified_layout")
            self.assertEqual(slots[2]["truth_status"], "unknown")
            self.assertIsNone(slots[2]["canonical_name"])
            # 裁剪文件：slot0/slot1 各 1 个 name crop；slot2 无 crop
            self.assertEqual(len(m["crops"]), 2)
            self.assertFalse(violations)
            for c in m["crops"]:
                self.assertTrue((out / c).exists(), c)

    def test_contact_sheet_builds(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            out = tmp / "fixtures"
            violations: list = []
            copies: list = []
            m = crp.process_entry(self._entry(tmp), out, violations, copies, crp.load_lexicon())
            manifest = {"entries": [m]}
            cs_dir = tmp / "contact"
            res = crp.build_contact_sheet(manifest, cs_dir, out)
            self.assertEqual(res["sheets"], 1)
            self.assertTrue((cs_dir / "index.html").exists())
            self.assertTrue((cs_dir / "index.json").exists())
            idx = json.loads((cs_dir / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(idx[0]["id"], "test_panel_1")
            self.assertTrue(idx[0]["unverified_layout"])  # slot2 unverified
            with Image.open(cs_dir / "test_panel_1.png") as sheet:
                self.assertGreater(sheet.width, 400)


class TestTruthHelpers(unittest.TestCase):
    def test_truth_status_and_canonical(self):
        lex = crp.load_lexicon()
        self.assertEqual(crp.truth_status_of("光法", lex), "in_lexicon")
        self.assertEqual(crp.truth_status_of("奥术激光", lex), "alias_covered")
        self.assertEqual(crp.truth_status_of("随便虚构", lex), "unknown")
        self.assertEqual(crp.truth_status_of(None, lex), "unknown")
        self.assertEqual(crp.canonical_for("奥术激光", lex), "奥数激光")
        self.assertIsNone(crp.canonical_for("随便虚构", lex))


if __name__ == "__main__":
    unittest.main()
