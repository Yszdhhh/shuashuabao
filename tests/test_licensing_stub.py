"""licensing stub：断网/过期 fail-closed。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.licensing import (  # noqa: E402
    Lease,
    evaluate_lease,
    issue_lease,
    machine_id,
)


class LicensingStubTests(unittest.TestCase):
    def test_issue_and_accept(self):
        now = 1_700_000_000.0
        lease = issue_lease(days=1, now=now)
        self.assertTrue(
            evaluate_lease(lease, now=now + 60, expected_machine_id=lease.machine_id)
        )

    def test_expired_without_grace(self):
        lease = Lease(machine_id="abc", expires_at=100.0, entitled=True)
        self.assertFalse(
            evaluate_lease(lease, now=101.0, expected_machine_id="abc", grace_seconds=0)
        )

    def test_grace_allows_short_offline(self):
        lease = Lease(machine_id="abc", expires_at=100.0, entitled=True)
        self.assertTrue(
            evaluate_lease(
                lease, now=100 + 3600, expected_machine_id="abc", grace_seconds=7200
            )
        )

    def test_wrong_machine_rejected(self):
        lease = Lease(machine_id="a", expires_at=9999999999.0, entitled=True)
        self.assertFalse(evaluate_lease(lease, expected_machine_id="b"))

    def test_none_lease_rejected(self):
        self.assertFalse(evaluate_lease(None))

    def test_machine_id_stable(self):
        self.assertEqual(machine_id(), machine_id())
        self.assertEqual(len(machine_id()), 32)


if __name__ == "__main__":
    unittest.main()
