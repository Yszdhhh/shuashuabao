from dataclasses import replace
import unittest

from shuabao.runtime_core.arbiter import Demand, TaskSpec
from shuabao.runtime_core.coordinator import ActionContract, Coordinator
from shuabao.runtime_core.transactions import Outcome, Phase, Proof


def p(gen, t, **changes):
    return replace(Proof(gen, t, "one-window", True, True, True, True), **changes)


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.c = Coordinator("r", (TaskSpec("skill", 0, 5, 8), TaskSpec("bag", 1, 10, 8)))
        self.ds = (Demand("skill", True, True, "v1"), Demand("bag", True, True, "v1"))
        self.g = self.c.propose(self.ds, 0, p(1, 0), input_safe=True).grant
        self.contract = ActionContract("select:1", "skill:ice", "skill_learned", True)

    def test_end_to_end_grant_dispatch_verify_receipt(self):
        self.c.dispatch(self.g.token, self.contract, 0, p(1, 0))
        self.c.observe_outcome(self.g.token, "skill_learned", 1, p(2, 1))
        receipt = self.c.finish(self.g.token, Outcome.CONFIRMED, 1, p(2, 1))
        self.assertIs(receipt.outcome, Outcome.CONFIRMED)
        self.assertIsNone(self.c.arbiter.active)
        self.assertIsNone(self.c.leases.current)
        self.assertEqual(self.c.arbiter.accounts["skill"].confirmed_count, 1)

    def test_new_proposal_does_not_confirm_pending_action(self):
        self.c.dispatch(self.g.token, self.contract, 0, p(1, 0))
        result = self.c.propose(self.ds, 1, p(2, 1), input_safe=True)
        self.assertIsNone(result.grant)
        self.assertIs(self.c.leases.current.phase, Phase.VERIFYING)

    def test_foreign_postcondition_rejected(self):
        self.c.dispatch(self.g.token, self.contract, 0, p(1, 0))
        with self.assertRaises(ValueError):
            self.c.observe_outcome(self.g.token, "random_frame_changed", 1, p(2, 1))

    def test_no_domain_authority_no_dispatch(self):
        with self.assertRaises(ValueError):
            self.c.dispatch(self.g.token, replace(self.contract, authorized=False), 0, p(1, 0))

    def test_backpack_cannot_preempt_pending_skill(self):
        self.c.dispatch(self.g.token, self.contract, 0, p(1, 0))
        result = self.c.propose((self.ds[1],), 1, p(2, 1), input_safe=True)
        self.assertIsNone(result.grant)
        self.assertEqual(self.c.leases.current.owner, "skill")

    def test_timeout_keeps_owner_without_input(self):
        self.c.dispatch(self.g.token, self.contract, 0, p(1, 0))
        self.c.observe_outcome(self.g.token, "skill_learned", 9, p(2, 9, postcondition=None))
        self.assertIs(self.c.leases.current.phase, Phase.RECONCILE)
        with self.assertRaises(RuntimeError):
            self.c.finish(self.g.token, Outcome.CONFIRMED, 9, p(2, 9))
        self.assertIsNotNone(self.c.arbiter.active)

    def test_unsafe_close_retains_both_owners(self):
        with self.assertRaises(RuntimeError):
            self.c.finish(self.g.token, Outcome.NO_PROGRESS, 1, p(2, 1, cursor_empty=False))
        self.assertIsNotNone(self.c.arbiter.active)
        self.assertIsNotNone(self.c.leases.current)

class AdditionalBoundaryTests(unittest.TestCase):
    def test_held_cursor_cannot_obtain_a_new_grant(self):
        c = Coordinator("r", (TaskSpec("bag", 1, 10, 8),))
        d = (Demand("bag", True, True, "v"),)
        self.assertIsNone(c.propose(d, 0, p(1, 0, cursor_empty=False), input_safe=True).grant)
        self.assertIsNone(c.leases.current)

    def test_compensation_cannot_renew_forever(self):
        from shuabao.runtime_core.transactions import LeaseBook
        b = LeaseBook()
        b.acquire("x", "bag", 0, 1, p(1, 0))
        b.dispatch("x", "pick", 0, p(1, 0))
        b.observe("x", 2, p(2, 2, postcondition=None))
        b.compensate("x", 2, 1, p(3, 2))
        b.observe("x", 4, p(4, 4, postcondition=None))
        with self.assertRaises(RuntimeError):
            b.compensate("x", 4, 1, p(5, 4))

    def test_late_success_receipt_refused(self):
        from shuabao.runtime_core.transactions import Receipt
        c = Coordinator("r", (TaskSpec("skill", 0, 5, 1),))
        g = c.propose((Demand("skill", True, True, "v"),), 0, p(1, 0), input_safe=True).grant
        with self.assertRaises(ValueError):
            c.arbiter.finish(Receipt(g.token, g.task, Outcome.CONFIRMED, 2, 2), 2)
        self.assertIsNotNone(c.arbiter.active)

    def test_deadline_miss_is_reported_not_hidden(self):
        c = Coordinator("r", (TaskSpec("skill", 0, 2, 1),))
        ds = (Demand("skill", True, True, "v"),)
        for t in range(4):
            c.arbiter.observe(ds, t, t + 1)
        self.assertTrue(c.arbiter.diagnostics(3)["skill"]["deadline_miss"])


if __name__ == "__main__":
    unittest.main()
