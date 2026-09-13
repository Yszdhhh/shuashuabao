"""lobby_hitch 隐藏默认值回归测试。

lobby_hitch.hidden_defaults 必须显式固定 auto_secret_realm=false，
防止其他模式的设置串入后走大秘境路径（CloudAudit 20260909 审查项 1）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.settings import Settings  # noqa: E402
from shuabao.shell.mode_catalog import apply_mode_overlay, get_spec  # noqa: E402


class LobbyHitchHiddenDefaultsTest(unittest.TestCase):
    def test_hidden_defaults_fix_auto_secret_realm_false(self):
        spec = get_spec("lobby_hitch")
        self.assertIs(spec.hidden_defaults["auto_secret_realm"], False)

    def test_overlay_overrides_auto_secret_realm_to_false(self):
        out = apply_mode_overlay(Settings(auto_secret_realm=True), "lobby_hitch")
        self.assertIs(out.auto_secret_realm, False)


if __name__ == "__main__":
    unittest.main()
