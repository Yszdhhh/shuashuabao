"""O3 离线门禁评测定向测试（无需 paddleocr）。

覆盖：
- session 隔离：train/val/test 按 session 切分，任一 session 只落一个 split（无帧级泄漏）；
- D0 复核记录：D0_vision_review.json 可 parse、逐槽 final 判定、truth 全部 canonical 或 unknown；
- 复核后 D0 manifest 与词典一致性：canonical 槽位的名称都能在词典中找到；
- O1 manifest 复核更新：原 17 个 unknown 槽中 16 个转 canonical、1 个显式 unknown；
- O3 新增负面板清单可 parse 且字段完整。

运行：.venv\\Scripts\\python.exe -m unittest tests.test_o3_gate -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import evaluate_o3_gate as o3  # noqa: E402
from shuabao.vision.choice_ocr import load_lexicon  # noqa: E402


class TestSessionSplit(unittest.TestCase):
    def test_every_session_in_exactly_one_split(self):
        all_sessions = set(o3.SPLIT["train"]) | set(o3.SPLIT["val"]) | set(o3.SPLIT["test"])
        self.assertEqual(
            len(all_sessions),
            len(o3.SPLIT["train"]) + len(o3.SPLIT["val"]) + len(o3.SPLIT["test"]),
            "session 不得跨 split 重复（帧级泄漏）",
        )
        self.assertEqual(len(all_sessions), 9)
        self.assertIn("rec9_mijing_20260810", o3.SPLIT["train"])
        self.assertIn("rec10_3normal_20260810", o3.SPLIT["train"])
        self.assertIn("rec5_260808", o3.SPLIT["test"])

    def test_unknown_session_marked_unknown_split(self):
        # 未知 session 不得被硬塞进某 split
        dataset = o3.build_dataset(o3.DEFAULT_O1_MANIFEST, o3.DEFAULT_D0_MANIFEST, o3.DEFAULT_REVIEW)
        for sl in dataset["slots"]:
            self.assertNotEqual(sl["split"], "?", f"{sl['entry_id']} has no split")
            self.assertIn(sl["split"], ("train", "val", "test"))


class TestReviewRecord(unittest.TestCase):
    def test_review_record_valid(self):
        r = json.loads(o3.DEFAULT_REVIEW.read_text(encoding="utf-8"))
        self.assertEqual(r["schema_version"], 1)
        self.assertTrue(r["slots"])
        for key, v in r["slots"].items():
            self.assertIn(v["final"], ("canonical", "unknown"), key)
            if v["final"] == "canonical":
                self.assertTrue(v["canonical"], key)
            else:
                self.assertIsNone(v["canonical"], key)
            self.assertIn("basis", v)
            self.assertIn("reviewer", v)

    def test_reviewed_canonicals_are_in_lexicon(self):
        """复核后 truth 全部为词典规范名或显式 unknown；与 choice_lexicon 一致性校验。"""
        lexicon = load_lexicon()
        d0 = json.loads(o3.DEFAULT_D0_MANIFEST.read_text(encoding="utf-8"))
        canonical = 0
        for e in d0["entries"]:
            for s in e.get("slots", []):
                if s.get("is_valid"):
                    canonical += 1
                    self.assertIn(s["canonical_name"], lexicon["entries"],
                                  f"{e['id']} slot {s['index']} canonical not in lexicon")
        self.assertGreaterEqual(canonical, 200)

    def test_o1_manifest_unknowns_reviewed(self):
        """O1 manifest：原 17 个 unknown 槽复核后 16 canonical + 1 显式 unknown。"""
        m = json.loads(o3.DEFAULT_O1_MANIFEST.read_text(encoding="utf-8"))
        unknown = []
        for e in m["entries"]:
            for s in e.get("slots", []):
                if s.get("truth_status") == "unknown":
                    unknown.append((e["id"], s["index"]))
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0][0], "rec5_260808_f_086_bond_corrected")
        # f_086 s1（力量之源→统计文本）保持 unknown
        note = [
            s.get("reviewed_by", "")
            for e in m["entries"] for s in e.get("slots", [])
            if e["id"] == "rec5_260808_f_086_bond_corrected" and s["index"] == 1
        ][0]
        self.assertIn("stat text", note)

    def test_dataset_stats(self):
        dataset = o3.build_dataset(o3.DEFAULT_O1_MANIFEST, o3.DEFAULT_D0_MANIFEST, o3.DEFAULT_REVIEW)
        slots = dataset["slots"]
        self.assertGreaterEqual(len(slots), 380)
        src = {}
        for sl in slots:
            src[sl["source"]] = src.get(sl["source"], 0) + 1
        self.assertGreaterEqual(src.get("d0", 0), 200)
        self.assertGreaterEqual(src.get("o1", 0), 150)


class TestNegativesExtra(unittest.TestCase):
    def test_neg_extra_manifest_valid(self):
        p = REPO_ROOT / "fixtures" / "ocr_choices" / "O3_negatives_extra.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data["entries"]), 10)
        for e in data["entries"]:
            self.assertEqual(e["panel_kind"], "negative")
            self.assertTrue(e["original_frame"])
            self.assertIn(e["session_id"], ("rec9_mijing_20260810", "rec10_3normal_20260810"))
            frame = REPO_ROOT / e["original_frame"]
            self.assertTrue(frame.exists(), e["original_frame"])


if __name__ == "__main__":
    unittest.main()
