"""P0 画像采集：纯函数解析 + 落盘边界。不点游戏、不写仓库 config。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.player_profile import (  # noqa: E402
    LiveLane,
    LiveLaneBusy,
    build_first_login,
    build_poster,
    classify_tab_window,
    detect_scan_kind,
    parse_attr_panel,
    parse_equipment,
    parse_skill_levels,
    upsert_first_login,
    verified_skill_levels,
    write_profile,
)

_TRUTH_BLOB = "奥术箭 Lv47 爆炎箭 8 剑气13级 普攻 18"


class SkillParseTests(unittest.TestCase):
    def test_known_account_levels(self):
        parsed = parse_skill_levels(_TRUTH_BLOB, conf=0.9)
        self.assertEqual(parsed["asj"]["level"], 47)
        self.assertEqual(parsed["byj"]["level"], 8)
        self.assertEqual(parsed["jq"]["level"], 13)
        self.assertEqual(parsed["asj"]["status"], "verified")
        self.assertEqual(verified_skill_levels(parsed)["asj"], 47)

    def test_card_name_does_not_steal_family(self):
        parsed = parse_skill_levels("解锁卡牌：奥术箭矢、火焰箭矢", conf=0.9)
        self.assertIsNone(parsed["asj"]["level"])
        self.assertEqual(parsed["asj"]["status"], "missing")

    def test_low_conf_is_unverified_not_settings_ready(self):
        parsed = parse_skill_levels(_TRUTH_BLOB, conf=0.2)
        self.assertEqual(parsed["asj"]["level"], 47)
        self.assertEqual(parsed["asj"]["status"], "unverified")
        self.assertEqual(verified_skill_levels(parsed), {})

    def test_level_over_50_discarded(self):
        parsed = parse_skill_levels("奥术箭 99", conf=0.9)
        self.assertIsNone(parsed["asj"]["level"])
        self.assertEqual(parsed["asj"]["status"], "rejected_bad_range")

    def test_empty_does_not_invent(self):
        parsed = parse_skill_levels("", conf=1.0)
        self.assertGreaterEqual(len(parsed), 16)
        self.assertTrue(all(row["level"] is None for row in parsed.values()))
        self.assertTrue(all(row["status"] == "missing" for row in parsed.values()))
        self.assertEqual(verified_skill_levels(parsed), {})


class AttrParseTests(unittest.TestCase):
    def test_basic_fields(self):
        text = "力量 12 敏捷 40 智力 8 攻击 120 攻速 150% 暴击 35 技能急速 20 掉宝率 10"
        parsed = parse_attr_panel(text, conf=0.9)
        self.assertEqual(parsed["strength"]["value"], 12)
        self.assertEqual(parsed["agility"]["value"], 40)
        self.assertEqual(parsed["intelligence"]["value"], 8)
        self.assertEqual(parsed["attack_speed"]["value"], 150)
        self.assertEqual(parsed["skill_haste"]["value"], 20)
        self.assertEqual(parsed["drop_rate"]["value"], 10)
        self.assertEqual(parsed["crit"]["status"], "verified")

    def test_over_cap_attack_speed_discarded(self):
        parsed = parse_attr_panel("攻速 1200%", conf=0.9)
        self.assertIsNone(parsed["attack_speed"]["value"])
        self.assertEqual(parsed["attack_speed"]["status"], "rejected_over_cap")
        self.assertEqual(parsed["attack_speed"]["cap"], 1000)

    def test_over_cap_skill_haste_discarded(self):
        parsed = parse_attr_panel("技能急速 90", conf=0.9)
        self.assertIsNone(parsed["skill_haste"]["value"])
        self.assertEqual(parsed["skill_haste"]["status"], "rejected_over_cap")
        self.assertEqual(parsed["skill_haste"]["cap"], 80)

    def test_haste_slash_uses_percent_not_raw(self):
        parsed = parse_attr_panel("技能急速 198/49.7%", conf=0.9)
        self.assertEqual(parsed["skill_haste"]["value"], 49.7)
        self.assertEqual(parsed["skill_haste"]["status"], "verified")

    def test_empty_attrs_not_guessed(self):
        parsed = parse_attr_panel("大厅房间列表", conf=1.0)
        self.assertTrue(all(row["value"] is None for row in parsed.values()))


class DetectKindTests(unittest.TestCase):
    def test_skills_page(self):
        self.assertEqual(detect_scan_kind("奥术箭 47 爆炎箭 8 剑气 13"), "skills")

    def test_tab_panel(self):
        self.assertEqual(detect_scan_kind("力量 10 敏捷 12 智力 8 攻速 100"), "attrs")

    def test_unknown_fail_closed(self):
        self.assertIsNone(detect_scan_kind("房间列表 快速加入"))

    def test_equipment_page(self):
        self.assertEqual(detect_scan_kind("存档 装备 一键分解 整理背包 165/240"), "equipment")

    def test_tab_panel_title(self):
        self.assertEqual(detect_scan_kind("属性面板 增幅属性 力量增幅 300%"), "attrs")


class EquipmentAndBindTests(unittest.TestCase):
    def test_labeled_power_and_enhance(self):
        parsed = parse_equipment("装备战力 12295 强化等级 630", conf=0.9)
        self.assertEqual(parsed["combat_power"]["value"], 12295)
        self.assertEqual(parsed["enhance_level"]["value"], 630)
        self.assertEqual(parsed["combat_power"]["status"], "verified")

    def test_does_not_guess_from_inventory_numbers(self):
        parsed = parse_equipment("54234 2899 0 165/240 Lv.62 Lv.55 60 90", conf=0.9)
        self.assertIsNone(parsed["combat_power"]["value"])
        self.assertIsNone(parsed["enhance_level"]["value"])
        self.assertEqual(parsed["combat_power"]["status"], "missing")

    def test_roi_texts_without_labels(self):
        parsed = parse_equipment("", conf=0.9, power_text="12295", enhance_text="630")
        self.assertEqual(parsed["combat_power"]["value"], 12295)
        self.assertEqual(parsed["enhance_level"]["value"], 630)

    def test_no_opt_in_skips_bind(self):
        payload = build_first_login(equipment={"combat_power": {"value": 12295}}, opt_in=False)
        self.assertTrue(payload["skipped"])
        self.assertFalse(payload["opt_in"])

    def test_bind_then_poster(self):
        skills = parse_skill_levels("奥术箭 Lv47 爆炎箭 Lv9 剑气 Lv13", conf=0.9)
        equip = parse_equipment("战力 12295 强化 630", conf=0.9)
        bind = build_first_login(equipment=equip, skills=skills, opt_in=True)
        poster = build_poster(
            bind=bind,
            tab_attrs=parse_attr_panel("力量 12 敏捷 40 智力 8 攻速 271 技能急速 198/49.7%", conf=0.9),
            tab_window="entry",
        )
        self.assertEqual(poster["combat_power"], 12295)
        self.assertEqual(poster["enhance_level"], 630)
        self.assertEqual(poster["top_skills"][0]["id"], "asj")
        self.assertEqual(poster["tab_window"], "entry")
        self.assertEqual(poster["tab_highlights"]["skill_haste"], 49.7)

    def test_poster_rejects_mid_run_tab(self):
        poster = build_poster(
            tab_attrs=parse_attr_panel("力量 12 技能急速 198/49.7%", conf=0.9),
            hud_text="1/5 00:20 杀敌 1771 属性面板",
        )
        self.assertEqual(poster["tab_window"], "mid_run")
        self.assertIsNone(poster["tab_highlights"]["skill_haste"])

    def test_poster_unknown_tab_not_used(self):
        poster = build_poster(
            tab_attrs=parse_attr_panel("力量 12 技能急速 49.7%", conf=0.9),
        )
        self.assertEqual(poster["tab_window"], "unknown")
        self.assertIsNone(poster["tab_highlights"]["strength"])

    def test_classify_entry_needs_two_start_signals(self):
        self.assertEqual(classify_tab_window("1/5 00:08 杀敌 0 属性面板"), "entry")
        self.assertEqual(classify_tab_window("属性面板 力量 12"), "unknown")
        self.assertEqual(classify_tab_window("3/5 属性面板"), "mid_run")

    def test_upsert_bind_merges_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            upsert_first_login(
                dest_dir=dest,
                equipment=parse_equipment("战力 12295 强化 630", conf=0.9),
                opt_in=True,
                day="20260815",
            )
            path = upsert_first_login(
                dest_dir=dest,
                skills=parse_skill_levels("奥术箭 Lv47", conf=0.9),
                opt_in=True,
                day="20260815",
            )
            body = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(body["equipment"]["combat_power"]["value"], 12295)
            self.assertEqual(body["skills"]["asj"]["level"], 47)


class WriteAndLockTests(unittest.TestCase):
    def test_write_stays_out_of_repo_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "profile"
            path = write_profile(
                "skills",
                {"skills": {"asj": {"name": "奥术箭", "level": 47, "status": "verified"}}},
                dest_dir=dest,
                day="20260814",
                frame_path="x.png",
            )
            self.assertEqual(path.name, "skill_levels_20260814.json")
            body = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(body["wrote_settings"])
            self.assertEqual(body["kind"], "skill_levels")
            self.assertFalse(str(path).startswith(str(ROOT / "config")))

    def test_refuse_repo_config_dir(self):
        with self.assertRaises(ValueError):
            write_profile("skills", {"skills": {}}, dest_dir=ROOT / "config")

    def test_live_lane_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "ShuaBao.live.lock"
            first = LiveLane("profile_scan", path=lock)
            first.acquire()
            try:
                second = LiveLane("lab_run", path=lock)
                with self.assertRaises(LiveLaneBusy):
                    second.acquire()
            finally:
                first.release()
            third = LiveLane("profile_scan", path=lock)
            third.acquire()
            third.release()
            self.assertFalse(lock.exists())

    def test_stale_lock_from_dead_pid_is_stolen(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "ShuaBao.live.lock"
            lock.write_text(json.dumps({"pid": 0, "owner": "dead"}), encoding="utf-8")
            lane = LiveLane("profile_scan", path=lock)
            lane.acquire()
            lane.release()
            self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
