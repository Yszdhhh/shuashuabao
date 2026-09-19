"""Small adapter seam joining scheduler grants to exclusive transaction receipts.

Local code supplies observations, domain authorization and existing act_* calls.
This class never invokes an executor or guesses a postcondition.
"""
from __future__ import annotations

from dataclasses import dataclass

from .arbiter import Arbiter, DEFAULT_TASKS, Decision, Demand, TaskSpec
from .transactions import Lease, LeaseBook, Outcome, Proof, Receipt


@dataclass(frozen=True)
class ActionContract:
    action_id: str
    target_id: str
    postcondition_id: str
    authorized: bool


class Coordinator:
    def __init__(self, round_id: str, specs: tuple[TaskSpec, ...] = DEFAULT_TASKS) -> None:
        self.arbiter = Arbiter(round_id, specs)
        self.leases = LeaseBook()
        self.pending_contract: ActionContract | None = None

    def propose(self, demands: tuple[Demand, ...], now: float,
                proof: Proof, *, input_safe: bool) -> Decision:
        self.arbiter.observe(demands, now, proof.generation)
        decision = self.arbiter.choose(
            now, input_safe=(input_safe is True and proof.cursor_empty is True
                        and proof.fresh(now, self.leases.max_proof_age)),
            owner=self.leases.current,
        )
        if decision.grant is not None:
            g = decision.grant
            self.leases.acquire(g.token, g.task, now, g.deadline - now, proof)
        return decision

    def dispatch(self, token: str, contract: ActionContract, now: float, proof: Proof) -> Lease:
        if (contract.authorized is not True or not contract.action_id
                or not contract.target_id or not contract.postcondition_id):
            raise ValueError("positive domain authorization and named postcondition required")
        lease = self.leases.dispatch(token, contract.action_id, now, proof)
        self.pending_contract = contract
        return lease

    def observe_outcome(self, token: str, postcondition_id: str, now: float, proof: Proof) -> Lease:
        if self.pending_contract is None or self.pending_contract.postcondition_id != postcondition_id:
            raise ValueError("unrelated postcondition cannot settle this action")
        return self.leases.observe(token, now, proof)

    def finish(self, token: str, outcome: Outcome, now: float, proof: Proof) -> Receipt:
        grant = self.arbiter.active
        if grant is None or token != grant.token or proof.generation < grant.generation:
            raise ValueError("no corresponding scheduler grant")
        receipt = self.leases.release(token, outcome, now, proof)
        self.arbiter.finish(receipt, now)
        self.pending_contract = None
        return receipt
