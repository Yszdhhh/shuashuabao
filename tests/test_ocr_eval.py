"""O0/O1 OCR 评测可信度定向测试。

覆盖：
- MODEL_MANIFEST.json 合法 JSON + 必需字段 + 可 parse；
- 模型字节篡改 → hash gate FAIL（真实 SHA256/大小计算，不硬编码 PASS）；
- 准确率分母 = 独立有效槽位（两轮推理不倍增分母）；
- repo HEAD 记录（git rev-parse HEAD 非空且 = 当前提交）；
- 词典外 truth 单独计 unknown，不进准确率分母；
- unverified_layout 槽不进准确率分母；
- 负面板 触发/分类/建议 链期望建议数 = 0（黑帧等真实负样本）；
- OCR 依赖锁（requirements-ocr.txt / requirements-ocr.lock）存在且固定 paddle 版本。

运行：.venv\\Scripts\\python.exe -m unittest tests.test_ocr_eval -v
（无需 paddleocr；本文件不导入 evaluate_choice_ocr 顶层 paddle 依赖路径）
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import evaluate_choice_ocr as evo  # noqa: E402
from shuabao.vision.choice_ocr import load_lexicon  # noqa: E402


class FakeRec:
    """paddleocr 的替身：固定返回文本（负面板建议阶段不需要真推理）。"""

    def __init__(self, text: str = "", score: float = 0.0):
        self._text = text
        self._score = score

    def predict_one(self, path):  # noqa: ANN001
        return {"text": self._text, "score": self._score, "seconds": 0.0}


class TestModelManifest(unittest.TestCase):
    def test_manifest_is_valid_json_with_required_fields(self):
        path = REPO_ROOT / "models" / "ocr" / "MODEL_MANIFEST.json"
        data = json.loads(path.read_text(encoding="utf-8"))  # 非法 JSON 会在此抛错
        self.assertEqual(data["schema_version"], 2)
        self.assertTrue(data["models"])
        for entry in data["models"]:
            for field in ("name", "license", "source_url"):
                self.assertIn(field, entry, f"{entry.get('name')} missing {field}")
            if entry.get("present_in_repo"):
                self.assertTrue(entry["model_dir"])
                self.assertTrue(entry["files"])
                for rel, spec in entry["files"].items():
                    self.assertTrue(spec["sha256"], f"{rel} missing sha256")
                    self.assertGreater(spec["size_bytes"], 0, f"{rel} missing size")
        # 解析器可用
        m = evo.load_model_manifest(path)
        self.assertEqual(len(m["models"]), 2)

    def test_mobile_entry_records_real_hashes(self):
        entry = evo.find_manifest_entry(
            evo.load_model_manifest(REPO_ROOT / "models" / "ocr" / "MODEL_MANIFEST.json"),
            "PP-OCRv5_mobile_rec_infer",
        )
        mdir = REPO_ROOT / "models" / "ocr" / "PP-OCRv5_mobile_rec_infer"
        for rel, spec in entry["files"].items():
            f = mdir / rel
            self.assertTrue(f.exists(), rel)
            self.assertEqual(f.stat().st_size, spec["size_bytes"], f"{rel} size mismatch")
            self.assertEqual(
                evo.sha256_file(f), spec["sha256"].upper(), f"{rel} sha256 mismatch"
            )


class TestHashGate(unittest.TestCase):
    def _staged_model_dir(self, flip: bool) -> Path:
        """把 mobile 模型 3 个文件复制到临时目录；flip=True 时翻转 pdiparams 1 字节。"""
        src = REPO_ROOT / "models" / "ocr" / "PP-OCRv5_mobile_rec_infer"
        tmp = Path(tempfile.mkdtemp(prefix="ocr_hashgate_")) / "PP-OCRv5_mobile_rec_infer"
        tmp.mkdir(parents=True)
        for f in ("inference.json", "inference.pdiparams", "inference.yml"):
            shutil.copy2(src / f, tmp / f)
        if flip:
            p = tmp / "inference.pdiparams"
            data = bytearray(p.read_bytes())
            data[0] ^= 0xFF
            p.write_bytes(bytes(data))
        return tmp

    def test_unmodified_model_passes(self):
        entry = evo.find_manifest_entry(
            evo.load_model_manifest(REPO_ROOT / "models" / "ocr" / "MODEL_MANIFEST.json"),
            "PP-OCRv5_mobile_rec_infer",
        )
        res = evo.verify_model_files(self._staged_model_dir(flip=False), entry)
        self.assertTrue(res["passed"], res)
        self.assertEqual(len(res["checks"]), 3)

    def test_tampered_model_fails_hash_gate(self):
        entry = evo.find_manifest_entry(
            evo.load_model_manifest(REPO_ROOT / "models" / "ocr" / "MODEL_MANIFEST.json"),
            "PP-OCRv5_mobile_rec_infer",
        )
        res = evo.verify_model_files(self._staged_model_dir(flip=True), entry)
        self.assertFalse(res["passed"], "tampered model must FAIL the hash gate")
        self.assertFalse(all(c["passed"] for c in res["checks"]))
        # 证据字段必须携带实际计算值
        tampered = next(c for c in res["checks"] if c["file"].endswith("inference.pdiparams"))
        self.assertNotEqual(
            tampered["actual_sha256"], tampered["expected_sha256"], "sha mismatch must be visible"
        )

    def test_missing_model_file_fails(self):
        entry = evo.find_manifest_entry(
            evo.load_model_manifest(REPO_ROOT / "models" / "ocr" / "MODEL_MANIFEST.json"),
            "PP-OCRv5_mobile_rec_infer",
        )
        tmp = Path(tempfile.mkdtemp(prefix="ocr_hashgate_")) / "PP-OCRv5_mobile_rec_infer"
        tmp.mkdir(parents=True)
        # 只复制 2/3 文件
        for f in ("inference.json", "inference.yml"):
            shutil.copy2(REPO_ROOT / "models" / "ocr" / "PP-OCRv5_mobile_rec_infer" / f, tmp / f)
        res = evo.verify_model_files(tmp, entry)
        self.assertFalse(res["passed"])
        missing = next(c for c in res["checks"] if not c.get("exists"))
        self.assertIn("missing", missing.get("error", ""))


class TestAccuracyDenominator(unittest.TestCase):
    def _lexicon(self):
        return load_lexicon()

    def _samples(self, rounds: int = 2, variant: str = "raw"):
        # 3 个唯一槽位（recA/s0,s1,s2）两轮 → 6 条样本；denominator 必须是 3
        out = []
        canon = ["天雷", "焦点", "箭矢齐射"]
        for r in range(rounds):
            for i, c in enumerate(canon):
                out.append(
                    {
                        "entry_id": "recA",
                        "session_id": "sessA",
                        "slot_index": i,
                        "round": r,
                        "kind": "skill",
                        "variant": variant,
                        "rec_text": c,  # 全部识别正确
                        "rec_score": 0.99,
                        "truth_raw": c,
                        "truth_canonical": c,
                        "is_dragon_ball": False,
                        "crop": f"recA_{i}.png",
                    }
                )
        return out

    def _manifest(self, slot_roi: dict | None = None, layout_status: str | None = None):
        slots = []
        for i in range(3):
            s = {
                "index": i,
                "canonical_name": ["天雷", "焦点", "箭矢齐射"][i],
                "raw_text": ["天雷", "焦点", "箭矢齐射"][i],
                "is_valid": True,
            }
            if slot_roi:
                s["roi"] = slot_roi
            if layout_status:
                s["layout_status"] = layout_status
            slots.append(s)
        return {"schema_version": 2, "entries": [{"id": "recA", "slots": slots}]}

    def test_denominator_is_unique_slots_not_rounds(self):
        m = self._manifest(slot_roi={"name": [0.2, 0.2, 0.4, 0.3]})
        metrics = evo.compute_metrics(self._samples(rounds=2), [], self._lexicon(), m)
        gl = metrics["variants"]["raw"]["gated_layer"]
        # 两轮推理但分母 = 3 个唯一槽，不是 6
        self.assertEqual(gl["in_lexicon_total"], 3)
        self.assertEqual(gl["canonical_top1_alias_aware"]["denominator"], 3)
        self.assertEqual(gl["canonical_top1_alias_aware"]["numerator"], 3)
        self.assertEqual(metrics["unique"]["valid_slots"], 3)
        self.assertEqual(metrics["stability"]["slots_compared"], 3)
        self.assertEqual(metrics["stability"]["stability_rate"], 1.0)

    def test_unknown_truth_excluded_from_accuracy(self):
        m = self._manifest(slot_roi={"name": [0.2, 0.2, 0.4, 0.3]})
        samples = self._samples(rounds=1)
        # 槽 1 的 truth 改成词典外名字
        samples[1]["truth_canonical"] = "完全不在词典的虚构名"
        metrics = evo.compute_metrics(samples, [], self._lexicon(), m)
        gl = metrics["variants"]["raw"]["gated_layer"]
        self.assertEqual(gl["in_lexicon_total"], 2)
        self.assertEqual(gl["out_of_lexicon_total"], 1)
        self.assertEqual(metrics["unique"]["unknown_slots"], 1)
        # 该槽不参与 Top-1 分母
        self.assertEqual(gl["canonical_top1_alias_aware"]["denominator"], 2)

    def test_unverified_layout_excluded_from_accuracy(self):
        # 槽 2 标 unverified_layout → 不进分母
        samples = self._samples(rounds=1)
        m = self._manifest()
        m["entries"][0]["slots"][2]["layout_status"] = "unverified_layout"
        metrics = evo.compute_metrics(samples, [], self._lexicon(), m)
        gl = metrics["variants"]["raw"]["gated_layer"]
        self.assertEqual(gl["unverified_layout_excluded"], 1)
        self.assertEqual(gl["in_lexicon_total"], 2)
        self.assertEqual(metrics["unique"]["unverified_layout_slots"], 1)
        self.assertEqual(gl["canonical_top1_alias_aware"]["denominator"], 2)

    def test_alias_covered_truth_corrected_and_counted(self):
        # 奥数激光 是 奥术激光 的别名 → truth_status=alias_covered，纠正后进分母
        samples = self._samples(rounds=1)
        samples[0]["truth_canonical"] = "奥数激光"
        samples[0]["truth_raw"] = "奥数激光"
        samples[0]["rec_text"] = "奥术激光"
        m = self._manifest(slot_roi={"name": [0.2, 0.2, 0.4, 0.3]})
        metrics = evo.compute_metrics(samples, [], self._lexicon(), m)
        gl = metrics["variants"]["raw"]["gated_layer"]
        self.assertEqual(metrics["unique"]["alias_covered_slots"], 1)
        self.assertEqual(gl["in_lexicon_total"], 3)
        # 纠正后的 truth=奥数激光，lookup 命中 → numerator 3/3
        self.assertEqual(gl["canonical_top1_alias_aware"]["numerator"], 3)

    def test_progress_and_latency_use_all_rounds(self):
        m = self._manifest(slot_roi={"name": [0.2, 0.2, 0.4, 0.3]})
        metrics = evo.compute_metrics(self._samples(rounds=2), [], self._lexicon(), m)
        self.assertEqual(metrics["variants"]["raw"]["raw_layer"]["slots"], 3)
        self.assertEqual(metrics["unique"]["valid_slots"], 3)


class TestRepoHead(unittest.TestCase):
    def test_repo_head_nonempty_and_current(self):
        info = evo.repo_head_info(REPO_ROOT)
        self.assertTrue(info["repo_head"], "repo_head must be non-empty")
        self.assertEqual(len(info["repo_head"]), 40)
        # 与 git rev-parse HEAD 一致
        import subprocess

        actual = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(info["repo_head"], actual)


class TestNegativeChain(unittest.TestCase):
    def test_black_frame_produces_zero_suggestions(self):
        """真实负样本（黑帧）跑完整 触发/分类/建议 链 → 建议数 0。"""
        entries = [
            e
            for e in json.loads(
                (REPO_ROOT / "fixtures" / "ocr_choices" / "manifest.json").read_text(encoding="utf-8")
            )["entries"]
            if e.get("panel_kind") == "negative"
        ]
        black = next(e for e in entries if "black_frame" in e["id"])
        images_dir = REPO_ROOT / "assets" / "Images"
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            res = evo.run_negative_chain(
                black, images_dir, FakeRec(), REPO_ROOT, Path(td)
            )
        self.assertFalse(res["anchor_triggered"])
        self.assertIsNone(res["classified_kind"])
        self.assertEqual(res["suggestion_count"], 0)
        self.assertTrue(res["passed"])

    def test_unknown_page_produces_zero_suggestions(self):
        entries = [
            e
            for e in json.loads(
                (REPO_ROOT / "fixtures" / "ocr_choices" / "manifest.json").read_text(encoding="utf-8")
            )["entries"]
            if e.get("panel_kind") == "negative"
        ]
        unk = next(e for e in entries if "unknown_page" in e["id"])
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            res = evo.run_negative_chain(
                unk, REPO_ROOT / "assets" / "Images", FakeRec(), REPO_ROOT, Path(td)
            )
        self.assertEqual(res["suggestion_count"], 0)
        self.assertTrue(res["passed"])

    def test_all_37_negatives_report_fields_complete(self):
        entries = [
            e
            for e in json.loads(
                (REPO_ROOT / "fixtures" / "ocr_choices" / "manifest.json").read_text(encoding="utf-8")
            )["entries"]
            if e.get("panel_kind") == "negative"
        ]
        self.assertEqual(len(entries), 37)
        for e in entries:
            for field in ("id", "original_frame", "negative_reason"):
                self.assertIn(field, e)


class TestDepLock(unittest.TestCase):
    def test_lock_files_exist_and_pin_versions(self):
        txt = (REPO_ROOT / "requirements-ocr.txt").read_text(encoding="utf-8")
        lock = (REPO_ROOT / "requirements-ocr.lock").read_text(encoding="utf-8")
        for pkg, ver in (("paddlepaddle", "3.3.1"), ("paddleocr", "3.7.0"), ("paddlex", "3.7.2")):
            self.assertIn(f"{pkg}=={ver}", txt)
            self.assertIn(f"{pkg}=={ver}", lock)


class TestLayoutStatus(unittest.TestCase):
    def test_slot_layout_status_rules(self):
        self.assertEqual(evo.slot_layout_status({"layout_status": "verified"}), "verified")
        self.assertEqual(evo.slot_layout_status({"layout_status": "unverified_layout"}), "unverified_layout")
        self.assertEqual(evo.slot_layout_status({"roi": {"name": [0, 0, 1, 1]}}), "verified")
        self.assertEqual(evo.slot_layout_status({}), "legacy")


if __name__ == "__main__":
    unittest.main()
