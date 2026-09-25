"""B 组：卡牌模板双向断言 + 负面宝物词典完备性。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "fixtures" / "card_template_assertions" / "templates_index.json"
CARDS = ROOT / "assets" / "Images" / "cards"
FETTER_LABELS = ROOT / "config" / "fetter_labels.json"
LEXICON = ROOT / "config" / "choice_lexicon.json"

NEGATIVE_TREASURES = (
    "透支力量",
    "贪婪献祭",
    "金转木",
    "杀敌梭哈",
    "伐木契约",
    "诅咒之力",
    "提高上限",
    "木材梭哈",
)


class CardTemplateInventoryTests(unittest.TestCase):
    def test_index_matches_disk_and_labels(self):
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        shortcodes = index["shortcodes"]
        self.assertEqual(len(shortcodes), index["count"])
        self.assertEqual(index["label_missing_for_template"], [])
        self.assertEqual(index["template_missing_for_label"], [])

        disk = sorted(p.stem for p in CARDS.glob("*.png"))
        self.assertEqual(disk, sorted(shortcodes))

        labels = json.loads(FETTER_LABELS.read_text(encoding="utf-8"))
        label_keys = sorted(k for k in labels if not str(k).startswith("_"))
        # Registered families whose template is captured on the next live run.
        pending = sorted(k for k in index.get("pending_live_capture", {}) if not k.startswith("_"))
        self.assertFalse(set(pending) & set(shortcodes))
        self.assertEqual(label_keys, sorted([*shortcodes, *pending]))

    def test_thresholds_present(self):
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        thr = index["thresholds"]
        self.assertGreaterEqual(thr["positive_min"], 0.9)
        self.assertLessEqual(thr["negative_max"], 0.4)
        self.assertTrue((ROOT / index["positive_frames"][0]).is_file())
        self.assertTrue((ROOT / index["negative_frames"][0]).is_file())


class CardBidirectionalTests(unittest.TestCase):
    def test_validate_scenes_card_bidir_passes(self):
        from tools.validate_scenes import validate_card_bidirectional

        _ok, fail, errors = validate_card_bidirectional()
        self.assertEqual(fail, 0, msg="\n".join(errors))

    def test_zhufu_panel_positive_and_blank_negative(self):
        # 必须用 imread_unicode：仓库目录含非 ASCII（🎮 影音游戏），
        # cv2.imread 在 Windows 上对这类路径静默返回 None。
        from tools.validate_scenes import _match_score, imread_unicode

        index = json.loads(INDEX.read_text(encoding="utf-8"))
        positive_min = float(index["thresholds"]["positive_min"])
        negative_max = float(index["thresholds"]["negative_max"])
        tpl = imread_unicode(CARDS / "zhufu.png")
        self.assertIsNotNone(tpl)

        bond = imread_unicode(
            ROOT / "fixtures/card_template_assertions/positives/bond_choice_3.png"
        )
        black = imread_unicode(
            ROOT / "fixtures/card_template_assertions/negatives/black_frame.png"
        )
        idle = imread_unicode(
            ROOT / "fixtures/card_template_assertions/negatives/idle_hud.png"
        )
        pos = _match_score(bond, tpl)
        blank = _match_score(black, tpl)
        unrelated = _match_score(idle, tpl)
        self.assertGreaterEqual(pos, positive_min, msg=f"zhufu panel pos={pos}")
        self.assertLessEqual(blank, negative_max, msg=f"zhufu blank={blank}")
        self.assertLess(
            unrelated,
            positive_min,
            msg=f"zhufu must not false-fire on idle_hud ({unrelated})",
        )


class NegativeTreasureLexiconTests(unittest.TestCase):
    def test_default_blocked_treasures_in_lexicon(self):
        data = json.loads(LEXICON.read_text(encoding="utf-8"))
        entries = data["entries"]
        for name in NEGATIVE_TREASURES:
            self.assertIn(name, entries)
            self.assertEqual(entries[name]["kind"], "treasure")

    def test_confirmed_ocr_aliases(self):
        from shuabao.vision.choice_ocr import lookup_lexicon

        self.assertEqual(lookup_lexicon("箭失增幅").canonical, "箭矢增幅")
        self.assertEqual(lookup_lexicon("箭失齐射").canonical, "箭矢齐射")
        self.assertEqual(lookup_lexicon("箭失连发").canonical, "箭矢连发")
        self.assertEqual(lookup_lexicon("制导箭失").canonical, "制导箭矢")
        self.assertEqual(lookup_lexicon("经验（中）").canonical, "经验(中)")
        self.assertEqual(lookup_lexicon("木材（小）").canonical, "木材(小)")
        self.assertEqual(lookup_lexicon("杀敌（小）").canonical, "杀敌(小)")


if __name__ == "__main__":
    unittest.main()
