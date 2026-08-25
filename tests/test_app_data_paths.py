from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class AppDataPathsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_canonical_path_default_and_env_override(self):
        from shuabao.paths import get_canonical_app_data_dir

        with patch.dict(os.environ, {"SHUABAO_APP_DATA": str(self.tmp_path / "custom_data")}):
            p = get_canonical_app_data_dir()
            self.assertEqual(p, (self.tmp_path / "custom_data").resolve())

        with patch.dict(os.environ, {}, clear=False):
            if "SHUABAO_APP_DATA" in os.environ:
                del os.environ["SHUABAO_APP_DATA"]
            with patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp_path / "local")}):
                p = get_canonical_app_data_dir()
                self.assertEqual(p, (self.tmp_path / "local" / "ShuaBao").resolve())

    def test_all_standard_path_accessors(self):
        from shuabao.paths import (
            get_canonical_app_data_dir,
            habit_preference_path,
            incidents_dir,
            learning_dir,
            live_lock_path,
            live_log_path,
            player_profile_dir,
            user_settings_path,
        )

        app_data = self.tmp_path / "appdata"
        self.assertEqual(user_settings_path(app_data), app_data / "user_settings.json")
        self.assertEqual(live_lock_path(app_data), app_data / "ShuaBao.live.lock")
        self.assertEqual(incidents_dir(app_data), app_data / "incidents")
        self.assertEqual(learning_dir(app_data), app_data / "learning")
        self.assertEqual(habit_preference_path(app_data), app_data / "habit_preference.json")
        self.assertEqual(player_profile_dir(app_data), app_data / "profiles")
        self.assertEqual(live_log_path(app_data), app_data / "live.log")

    def test_migration_from_legacy_paths_is_idempotent_and_non_destructive(self):
        from shuabao.paths import migrate_legacy_data

        target = self.tmp_path / "target_appdata"
        target.mkdir(parents=True, exist_ok=True)

        legacy_dir = self.tmp_path / "legacy_appdata_zh"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "user_settings.json").write_text(json.dumps({"key": "from_legacy"}), encoding="utf-8")
        (legacy_dir / "habit_preference.json").write_text(json.dumps({"pref": 1}), encoding="utf-8")

        # Run migration with legacy_dir provided in candidates
        migrated = migrate_legacy_data(target_dir=target, extra_candidates=[legacy_dir])
        self.assertTrue(len(migrated) >= 2)

        # Verify target received files
        self.assertTrue((target / "user_settings.json").is_file())
        self.assertTrue((target / "habit_preference.json").is_file())
        self.assertEqual(json.loads((target / "user_settings.json").read_text(encoding="utf-8"))["key"], "from_legacy")

        # Source files must NOT be deleted
        self.assertTrue((legacy_dir / "user_settings.json").is_file())

        # Second migration must NOT overwrite target if target already exists
        (legacy_dir / "user_settings.json").write_text(json.dumps({"key": "overwritten_in_source"}), encoding="utf-8")
        migrated_again = migrate_legacy_data(target_dir=target, extra_candidates=[legacy_dir])
        self.assertEqual(len(migrated_again), 0)
        self.assertEqual(json.loads((target / "user_settings.json").read_text(encoding="utf-8"))["key"], "from_legacy")


if __name__ == "__main__":
    unittest.main()
