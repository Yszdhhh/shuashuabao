"""Zero-input protocol tests. Synthetic state is never marked LIVE."""
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import unittest

from shuabao.runtime_core.arbiter import Arbiter, Demand, TaskSpec
from shuabao.runtime_core.transactions import LeaseBook, Outcome, Phase, Proof, Receipt
from shuabao.runtime_core.contracts import (
    CardInstance, DeckFacts, ItemFact, ItemKind, Location, ResourceBudget,
    SlotBudget, active_group, authorize_consumption, destination,
)
from shuabao.runtime_core.evidence import (
    RunIdentity, canonical_hash, method_rebindings, validate_live_record,
    verify_bundle_files, file_hash,
)


def proof(gen=1, now=0.0, **kw):
    fields = dict(generation=gen, captured_at=now, epoch="hwnd:1/scale:1",
                  valid=True, postcondition=True, cursor_empty=True, surface_released=True)
    fields.update(kw)
    return Proof(**fields)


class Transactions(unittest.TestCase):
    def setUp(self):
        self.book = LeaseBook()
        self.book.acquire("round:1", "skill", 0, 8, proof())

    def test_second_owner_rejected(self):
        with self.assertRaises(RuntimeError):
            self.book.acquire("round:2", "bag", 1, 8, proof(2, 1))

    def test_wrong_owner_token_rejected(self):
        with self.assertRaises(ValueError):
            self.book.dispatch("other", "click", 1, proof(2, 1))

    def test_click_is_not_success(self):
        self.book.dispatch("round:1", "click", 0, proof())
        with self.assertRaises(RuntimeError):
            self.book.release("round:1", Outcome.CONFIRMED, 1, proof(2, 1))
        self.assertEqual(self.book.current.confirmed_steps, 0)

    def test_same_frame_cannot_confirm(self):
        self.book.dispatch("round:1", "click", 0, proof())
        self.book.observe("round:1", 1, proof(1, 1))
        self.assertIs(self.book.current.phase, Phase.VERIFYING)

    def test_missing_or_invalid_evidence_cannot_confirm(self):
        self.book.dispatch("round:1", "click", 0, proof())
        for p in (proof(2, 1, valid=False), proof(3, 1, postcondition=None)):
            self.book.observe("round:1", 1, p)
            self.assertEqual(self.book.current.confirmed_steps, 0)

    def test_stale_or_future_evidence_rejected(self):
        self.book.dispatch("round:1", "click", 0, proof())
        for p in (proof(2, 0), proof(3, 5)):
            self.book.observe("round:1", 3, p)
            self.assertEqual(self.book.current.confirmed_steps, 0)

    def test_epoch_change_requires_reconciliation(self):
        self.book.dispatch("round:1", "click", 0, proof())
        self.book.observe("round:1", 1, proof(2, 1, epoch="hwnd:2"))
        self.assertIs(self.book.current.phase, Phase.RECONCILE)

    def test_expiry_never_releases_owner(self):
        self.book.dispatch("round:1", "click", 0, proof())
        self.book.observe("round:1", 9, proof(2, 9))
        self.assertIs(self.book.current.phase, Phase.RECONCILE)
        with self.assertRaises(RuntimeError):
            self.book.acquire("round:2", "bag", 9, 2, proof(3, 9))

    def test_cursor_held_cannot_release(self):
        self.book.dispatch("round:1", "pick", 0, proof())
        self.book.observe("round:1", 1, proof(2, 1))
        for empty in (False, None):
            with self.subTest(empty=empty), self.assertRaises(RuntimeError):
                self.book.release("round:1", Outcome.CONFIRMED, 1, proof(2, 1, cursor_empty=empty))

    def test_surface_still_open_cannot_release(self):
        self.book.dispatch("round:1", "pick", 0, proof())
        self.book.observe("round:1", 1, proof(2, 1))
        with self.assertRaises(RuntimeError):
            self.book.release("round:1", Outcome.CONFIRMED, 1, proof(2, 1, surface_released=False))

    def test_multiple_steps_share_one_owner(self):
        for i, action in enumerate(("pick", "place", "close")):
            self.book.dispatch("round:1", action, i * 2, proof(1 + i * 2, i * 2))
            self.book.observe("round:1", i * 2 + 1, proof(2 + i * 2, i * 2 + 1))
        receipt = self.book.release("round:1", Outcome.CONFIRMED, 5, proof(6, 5))
        self.assertEqual(receipt.owner, "skill")
        self.assertIsNone(self.book.current)

    def test_confirmed_receipt_needs_business_step(self):
        with self.assertRaises(RuntimeError):
            self.book.release("round:1", Outcome.CONFIRMED, 1, proof(2, 1))

    def test_no_progress_receipt_is_not_confirmation(self):
        result = self.book.release("round:1", Outcome.NO_PROGRESS, 1, proof(2, 1))
        self.assertIs(result.outcome, Outcome.NO_PROGRESS)

    def test_compensation_is_not_business_success(self):
        self.book.dispatch("round:1", "pick", 0, proof())
        self.book.observe("round:1", 1, proof(2, 1, postcondition=False))
        self.book.compensate("round:1", 2, 4, proof(3, 2))
        self.book.dispatch("round:1", "return_to_source", 2, proof(3, 2))
        self.book.observe("round:1", 3, proof(4, 3))
        with self.assertRaises(RuntimeError):
            self.book.release("round:1", Outcome.CONFIRMED, 3, proof(4, 3))
        self.assertIs(self.book.release("round:1", Outcome.ABORTED_SAFE, 3, proof(4, 3)).outcome,
                      Outcome.ABORTED_SAFE)

    def test_token_cannot_be_reused(self):
        self.book.release("round:1", Outcome.NO_PROGRESS, 1, proof(2, 1))
        with self.assertRaises(ValueError):
            self.book.acquire("round:1", "skill", 2, 4, proof(3, 2))

    def test_clock_regression_rejected(self):
        self.book.observe("round:1", 2, proof(2, 2))
        with self.assertRaises(ValueError):
            self.book.observe("round:1", 1, proof(3, 1))


class Scheduling(unittest.TestCase):
    SPECS = (TaskSpec("bond", 0, 10, 2, 2, 8), TaskSpec("skill", 1, 6, 2, 2, 8),
             TaskSpec("pickup", 2, 8, 1, 2, 8))

    def setUp(self):
        self.a = Arbiter("run", self.SPECS)
        self.demands = tuple(Demand(s.name, True, True, "rev:1") for s in self.SPECS)

    def settle(self, grant, at, gen, outcome=Outcome.CONFIRMED):
        self.a.finish(Receipt(grant.token, grant.task, outcome, gen, at), at)

    def test_determinism(self):
        other = Arbiter("run", self.SPECS)
        for a in (self.a, other):
            a.observe(self.demands, 0, 1)
        self.assertEqual(self.a.choose(0, input_safe=True), other.choose(0, input_safe=True))

    def test_unknown_surface_zero_input(self):
        self.a.observe(self.demands, 0, 1)
        self.assertIsNone(self.a.choose(0, input_safe=False).grant)

    def test_stale_observation_zero_input(self):
        self.a.observe(self.demands, 0, 1)
        self.assertIsNone(self.a.choose(4, input_safe=True).grant)

    def test_repeated_generation_rejected(self):
        self.a.observe(self.demands, 0, 1)
        with self.assertRaises(ValueError):
            self.a.observe(self.demands, 1, 1)

    def test_unknown_and_duplicate_tasks_rejected(self):
        for ds in ((Demand("oops", True, True, "v"),), self.demands + self.demands):
            with self.subTest(ds=ds), self.assertRaises(ValueError):
                self.a.observe(ds, 0, 1)

    def test_blocked_task_requires_explanation(self):
        with self.assertRaises(ValueError):
            self.a.observe((Demand("skill", True, False, "v"),), 0, 1)

    def test_grant_expiry_is_not_auto_release(self):
        self.a.observe(self.demands, 0, 1)
        self.a.choose(0, input_safe=True)
        result = self.a.choose(9, input_safe=True)
        self.assertIsNone(result.grant)
        self.assertEqual(result.reason, "grant_requires_reconcile")

    def test_existing_transaction_has_exclusive_ownership(self):
        book = LeaseBook()
        lease = book.acquire("other", "bag", 0, 2, proof())
        self.a.observe(self.demands, 0, 1)
        self.assertEqual(self.a.choose(0, input_safe=True, owner=lease).reason, "owner_continuation")
        self.assertEqual(self.a.choose(3, input_safe=True, owner=lease).reason, "owner_requires_reconcile")

    def test_foreign_receipt_cannot_release_grant(self):
        self.a.observe(self.demands, 0, 1)
        self.a.choose(0, input_safe=True)
        with self.assertRaises(ValueError):
            self.a.finish(Receipt("other", "bond", Outcome.CONFIRMED, 2, 1), 1)
        self.assertIsNotNone(self.a.active)

    def test_aged_deadline_beats_high_priority(self):
        for t in range(10):
            self.a.observe(self.demands, t, t + 1)
        result = self.a.choose(9, input_safe=True)
        self.assertEqual(result.grant.task, "skill")
        self.assertEqual(result.reason, "deadline_service")

    def test_boss_blocked_bag_does_not_accrue_eligible_time(self):
        for t in range(20):
            self.a.observe((Demand("pickup", True, False, "v", "boss_busy"),), t, t + 1)
        d = self.a.diagnostics(19)["pickup"]
        self.assertEqual(d["wall_wait"], 19)
        self.assertEqual(d["eligible_wait"], 0)
        self.assertEqual(d["blocked_reason"], "boss_busy")

    def test_no_progress_backoff_then_revision_circuit(self):
        ds = (Demand("skill", True, True, "same_candidates"),)
        gen = 1
        now = 0.0
        for failure in range(3):
            self.a.observe(ds, now, gen)
            grant = self.a.choose(now, input_safe=True).grant
            self.assertIsNotNone(grant)
            self.settle(grant, now + 1, gen + 1, Outcome.NO_PROGRESS)
            now += 1
            self.a.observe(ds, now, gen + 2)
            self.assertIsNone(self.a.choose(now, input_safe=True).grant)
            now += min(8, 2 * 2 ** failure)
            gen += 3
        self.a.observe(ds, now + 100, gen)
        self.assertIsNone(self.a.choose(now + 100, input_safe=True).grant)
        self.assertTrue(self.a.diagnostics(now + 100)["skill"]["circuit_open"])
        self.a.observe((replace(ds[0], revision="new_candidates"),), now + 101, gen + 1)
        self.assertIsNotNone(self.a.choose(now + 101, input_safe=True).grant)

    def test_success_requires_fresh_readmission(self):
        self.a.observe(self.demands, 0, 1)
        g = self.a.choose(0, input_safe=True).grant
        self.settle(g, 1, 2)
        self.assertIsNone(self.a.choose(1, input_safe=True).grant)

    def test_continuous_high_wood_does_not_starve_other_tasks(self):
        # 600 ticks; service duration bounded by each task's quantum.
        services = {s.name: [] for s in self.SPECS}
        due = None
        for t in range(600):
            self.a.observe(self.demands, t, t + 1)
            if due is not None and t >= due.deadline:
                # Receipt describes a safe completion before the next tick.
                self.a.finish(Receipt(due.token, due.task, Outcome.CONFIRMED, t + 1, t - 0.25), t)
                services[due.task].append(t)
                due = None
                continue
            if due is None:
                due = self.a.choose(t, input_safe=True).grant
        for task, times in services.items():
            self.assertGreater(len(times), 10, task)
            self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), 16, task)

    def test_missing_observation_preserves_wall_age(self):
        self.a.observe(self.demands, 0, 1)
        self.a.observe((), 2, 2)
        self.assertEqual(self.a.diagnostics(2)["skill"]["wall_wait"], 2)

    def test_registry_rejects_invalid_budgets(self):
        for wait in (0, -1, math.inf, math.nan):
            with self.subTest(wait=wait), self.assertRaises(ValueError):
                TaskSpec("skill", 0, wait, 1)

    def test_round_reset_is_a_new_object(self):
        self.a.observe(self.demands, 10, 1)
        self.a.choose(10, input_safe=True)
        b = Arbiter("next", self.SPECS)
        self.assertIsNone(b.active)
        self.assertEqual(b.accounts["skill"].service_count, 0)


class DomainContracts(unittest.TestCase):
    def setUp(self):
        self.item = ItemFact("pill:1", ItemKind.PILL, "self", Location.PERSONAL_BAG)
        self.card = CardInstance("card:1", "pirate.filler", "pirate", 1)
        self.kw = dict(explicitly_enabled=True, solo=True, target_set_complete=True,
                       mechanism_verified=True, transaction_active=False, proof=proof(), now=0)

    def allow(self, **changes):
        return authorize_consumption(self.item, (self.card,), **(self.kw | changes))

    def test_disabled_cannot_be_overridden_by_deck_configuration(self):
        self.assertFalse(self.allow(explicitly_enabled=False).allowed)

    def test_random_set_with_one_protected_card_denied(self):
        core = replace(self.card, instance_id="core", canonical_id="pirate.admiral_rogers")
        self.assertFalse(authorize_consumption(self.item, (self.card, core), **self.kw).allowed)

    def test_ur_bounty_cannot_eat_rogers_or_warship(self):
        bounty = replace(self.item, kind=ItemKind.BOUNTY, rarity=5)
        for name in ("pirate.admiral_rogers", "pirate.destruction_warship"):
            core = replace(self.card, canonical_id=name, rarity=5)
            with self.subTest(name=name):
                self.assertFalse(authorize_consumption(bounty, (core,), **self.kw).allowed)

    def test_unknown_bounty_is_not_max_quality(self):
        self.assertFalse(authorize_consumption(replace(self.item, kind=ItemKind.BOUNTY),
                                              (self.card,), **self.kw).allowed)

    def test_known_bounty_quality_boundaries(self):
        for item_tier in range(1, 6):
            for target_tier in range(1, 6):
                with self.subTest(item=item_tier, target=target_tier):
                    item = replace(self.item, kind=ItemKind.BOUNTY, rarity=item_tier)
                    target = replace(self.card, rarity=target_tier)
                    self.assertEqual(authorize_consumption(item, (target,), **self.kw).allowed,
                                     target_tier <= item_tier)

    def test_team_asset_in_personal_bag_is_still_team_asset(self):
        self.assertFalse(authorize_consumption(replace(self.item, owner="team"),
                                              (self.card,), **self.kw).allowed)

    def test_other_transaction_blocks_consumption(self):
        self.assertFalse(self.allow(transaction_active=True).allowed)

    def test_missing_target_mechanism_denied(self):
        for kw in ({"target_set_complete": False}, {"mechanism_verified": False},
                   {"proof": proof(valid=False)}, {"solo": False}):
            self.assertFalse(self.allow(**kw).allowed)

    def test_god_pill_needs_ex_not_pirate_history(self):
        item = replace(self.item, kind=ItemKind.GOD_PILL)
        self.assertFalse(authorize_consumption(item, (self.card,), **self.kw).allowed)
        self.assertTrue(authorize_consumption(item, (replace(self.card, rarity=6),), **self.kw).allowed)

    def test_unknown_item_never_treated_as_equipment(self):
        self.assertIs(destination(replace(self.item, kind=ItemKind.UNKNOWN)), Location.DEFER)

    def test_consumables_default_to_personal_bag(self):
        self.assertIs(destination(self.item), Location.PERSONAL_BAG)

    def test_equipment_requires_positive_known_compatibility(self):
        for compatible, gain, expected in (
            (None, 10, Location.DEFER), (False, 10, Location.PERSONAL_BAG),
            (True, -1, Location.PERSONAL_BAG), (True, 1, Location.ITEM_BAR),
            (True, math.nan, Location.PERSONAL_BAG),
        ):
            item = replace(self.item, kind=ItemKind.EQUIPMENT, compatible=compatible, marginal_gain=gain)
            self.assertIs(destination(item), expected)

    def test_artifact_not_automatically_highest_bar_resident(self):
        item = replace(self.item, kind=ItemKind.ARTIFACT)
        self.assertIs(destination(item), Location.DEFER)
        self.assertIs(destination(replace(item, bar_effect_verified=True)), Location.ITEM_BAR)

    def test_slot_budget_uses_current_instances_not_history(self):
        for size in (6, 8, 10):
            cards = tuple(replace(self.card, instance_id=str(i)) for i in range(size))
            budget = SlotBudget(10, cards, reserved_peak=2)
            self.assertEqual(budget.free_slots, 10 - size)
            self.assertEqual(budget.admits_filler(), size <= 6)
        with self.assertRaises(ValueError):
            SlotBudget(10, tuple(replace(self.card, instance_id=str(i)) for i in range(12)))

    def test_bypass_base_does_not_bypass_advanced_order(self):
        facts = DeckFacts(frozenset({"growth"}), frozenset(),
                          frozenset({"pirate", "necromancy"}), frozenset())
        order = ("pirate", "treasure", "necromancy")
        self.assertEqual(active_group(facts, order)[1], "base_pending")
        self.assertEqual(active_group(facts, order, bypass_base=True)[0], "pirate")

    def test_locked_treasure_is_not_enabled_by_pirate_configuration(self):
        facts = DeckFacts(frozenset(), frozenset(), frozenset({"pirate", "necromancy"}),
                          frozenset({"pirate"}))
        self.assertEqual(active_group(facts, ("pirate", "treasure", "necromancy"))[0], "necromancy")
        facts = replace(facts, unlocked_groups=facts.unlocked_groups | {"treasure"})
        self.assertEqual(active_group(facts, ("pirate", "treasure", "necromancy"))[0], "treasure")

    def test_paused_is_not_completed(self):
        facts = DeckFacts(frozenset(), frozenset(), frozenset({"pirate"}), frozenset(),
                          frozenset({"pirate"}))
        self.assertEqual(active_group(facts, ("pirate",)), (None, "locked_or_paused"))

    def test_unknown_resource_is_not_spend_authority(self):
        self.assertFalse(ResourceBudget(None).affordable(20))
        self.assertFalse(ResourceBudget(20, 5).affordable(20))
        self.assertTrue(ResourceBudget(25, 5).affordable(20))


class Evidence(unittest.TestCase):
    def setUp(self):
        self.identity = RunIdentity("a" * 40, "b" * 40, "c" * 40,
                                    "d" * 64, "e" * 64, "f" * 64, "0" * 64)
        self.record = self.identity.to_dict() | {
            "evidence_kind": "LIVE", "manual_intervention": False,
            "worktree_clean_start": True, "worktree_clean_end": True,
            "manifest": "manifest.json", "run_log": "run.log",
            "before_frame": "before.png", "after_frame": "after.png",
            "action_id": "action:1", "postcondition_id": "target_equipped",
            "before_generation": 1, "after_generation": 2,
            "postcondition_confirmed": True, "status": "PASS",
        }

    def test_record_validity_is_not_gameplay_certification(self):
        self.assertEqual(validate_live_record(self.record, self.identity), ())

    def test_old_candidate_refused(self):
        errors = validate_live_record(self.record | {"candidate_sha": "e" * 40}, self.identity)
        self.assertIn("identity_mismatch:candidate_sha", errors)

    def test_changed_binding_same_candidate_refused(self):
        errors = validate_live_record(self.record | {"bindings_hash": "1" * 64}, self.identity)
        self.assertIn("identity_mismatch:bindings_hash", errors)

    def test_non_live_evidence_never_upgraded(self):
        for kind in ("UNIT", "FROZEN_REPLAY", "WHATIF", "PROFILE", "PROBE", "SHADOW"):
            with self.subTest(kind=kind):
                self.assertIn("not_live_evidence", validate_live_record(self.record | {"evidence_kind": kind}, self.identity))

    def test_not_observed_and_manual_intervention_are_not_pass(self):
        for override in ({"status": "NOT_OBSERVED"}, {"manual_intervention": True},
                         {"postcondition_confirmed": False}, {"worktree_clean_end": False}):
            self.assertTrue(validate_live_record(self.record | override, self.identity))

    def test_same_frame_is_not_postcondition(self):
        self.assertIn("postcondition_not_from_new_frame", validate_live_record(
            self.record | {"after_generation": 1}, self.identity))

    def test_file_evidence_checks_bytes_and_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            hashes = {}
            for key in ("manifest", "run_log", "before_frame", "after_frame"):
                p = root / self.record[key]
                p.write_text("synthetic-test-bytes", encoding="utf-8")
                hashes[self.record[key]] = file_hash(p)
            self.assertEqual(verify_bundle_files(self.record, root, hashes), ())
            (root / "run.log").write_text("changed", encoding="utf-8")
            self.assertIn("artifact_hash_mismatch:run_log", verify_bundle_files(self.record, root, hashes))
            self.assertTrue(verify_bundle_files(self.record | {"manifest": "../escape"}, root, hashes))

    def test_hash_is_order_independent_and_nan_refused(self):
        self.assertEqual(canonical_hash({"a": 1, "b": 2}), canonical_hash({"b": 2, "a": 1}))
        with self.assertRaises(ValueError):
            canonical_hash({"bad": math.nan})

    def test_monkeypatch_detection(self):
        source = "def f():\n    RuntimeMediator._maybe_use_inventory_item = Mediator._maybe_use_inventory_item\n"
        self.assertTrue(method_rebindings(source))
        self.assertTrue(method_rebindings("setattr(RuntimeMediator, 'method', other)"))
        self.assertFalse(method_rebindings("def f():\n    return RuntimeMediator()\n"))

    def test_identity_hash_shape_validation(self):
        with self.assertRaises(ValueError):
            replace(self.identity, candidate_sha="short")


if __name__ == "__main__":
    unittest.main()
