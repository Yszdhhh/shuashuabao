#!/usr/bin/env python3
"""Long-run synthetic audit of production round-boundary state ownership.

This drives the production LiveMediator boundary methods with the repository's
existing FakeClock/FakeInputExecutor/ActionProbe.  It never calls SendInput and
does not implement a second FSM.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import SessionState  # noqa: E402
from shuabao.interaction_surface import PendingAction  # noqa: E402
from shuabao.mediator import (  # noqa: E402
    PanelState,
    Phase,
    RecoveryKind,
    RecoveryState,
    RecoveryStep,
)
from shuabao.policy.equipment_fsm import EquipmentFSM  # noqa: E402
from shuabao.policy.merchant_fsm import MerchantFSM  # noqa: E402
from shuabao.runtime_mediator import Mediator  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.vision.capture import Frame  # noqa: E402
from tests.test_scenario_replay import (  # noqa: E402
    ActionProbe,
    FakeClock,
    FakeInputExecutor,
    ReplayFrameSource,
)


def _load_unknown_frames(rounds: int) -> list[Frame]:
    path = ROOT / "tests" / "performance" / "fixtures" / "unknown_page.png"
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(path)
    return [
        Frame(image.copy(), window_title="英雄三国KK", hwnd=10001)
        for _ in range(rounds)
    ]


def _pollute_round_state(med: Mediator, now: float) -> None:
    med._choice_session = SessionState(attempts=3, refreshes=2, waits=4)
    med._pending_action = PendingAction(
        kind="WAIT_AUDIT",
        target_id="audit",
        deadline=now + 100.0,
        verifier=lambda *_args, **_kwargs: False,
    )
    med._pending_action_unconfirmed_count = 2
    med._panel_state = PanelState.COOLDOWN
    med._panel_pending_choice_action = "select"
    med._panel_pending_choice_fingerprint = ("skill", "audit", 1, 1)
    med._selection_repeat_key = ("skill", "audit", 1, 1)
    med._selection_repeat_attempts = 2
    med._panel_cooldown_until = {"skill": now + 100.0}
    med._challenge_attempts = {"coin_challenge": 3}
    med._selection_click_cooldown_until = now + 100.0
    med._stage_click_cooldown_until = now + 100.0
    med._runtime_watchdog_hud_confirmations = 2
    med._runtime_watchdog_last_frame_id = 123
    med._runtime_watchdog_esc_attempts = 2
    med._recovery_state = RecoveryState(
        kind=RecoveryKind.FAIL,
        step=RecoveryStep.FAIL_CONFIRM,
        started_at=now,
        deadline=now + 100.0,
    )
    med._recovery_step = "FAIL_CONFIRM"
    med._equipment_fsm = EquipmentFSM().begin(2, now, fingerprint="equipment-old")
    med._merchant_fsm = (
        MerchantFSM()
        .observe(True, "merchant-old", now)
        .observe(True, "merchant-old", now + 0.1)
        .begin_purchase(now + 0.2, timeout_s=10.0)
    )


def run_audit(rounds: int) -> dict:
    if rounds < 10:
        raise ValueError("rounds must be >= 10")

    clock = FakeClock(start=1000.0)
    # Exercise LIVE decision semantics while the fake executor is the hard
    # boundary that makes real input impossible.
    med = Mediator(Settings(dry_run=False, ocr_mode="off"), ROOT)
    executor = FakeInputExecutor(med.stop_signal, clock)
    med.executor = executor
    actions = ActionProbe(med)
    frames = ReplayFrameSource(_load_unknown_frames(rounds))
    med._capture_best = frames.capture_best

    med._failure_streak = 2
    med._success_count = 7
    med._hitch_blacklisted_room_keys = {"session-room"}
    session_expected = {
        "_failure_streak": 2,
        "_success_count": 7,
        "_hitch_blacklisted_room_keys": {"session-room"},
    }
    clean_expected = {
        "_choice_session": SessionState(),
        "_pending_action": None,
        "_pending_action_unconfirmed_count": 0,
        "_panel_pending_choice_action": None,
        "_panel_pending_choice_fingerprint": None,
        "_selection_repeat_key": None,
        "_selection_repeat_attempts": 0,
        "_panel_cooldown_until": {},
        "_challenge_attempts": {},
        "_selection_click_cooldown_until": 0.0,
        "_stage_click_cooldown_until": 0.0,
        "_runtime_watchdog_hud_confirmations": 0,
        "_runtime_watchdog_last_frame_id": None,
        "_runtime_watchdog_esc_attempts": 0,
        "_recovery_state": None,
        "_recovery_step": None,
        "_equipment_fsm": EquipmentFSM(),
        "_merchant_fsm": MerchantFSM(),
    }
    findings: dict[str, dict] = {}
    unknown_zero_input_rounds = 0

    with clock.install(), contextlib.redirect_stdout(io.StringIO()):
        med.set_phase(Phase.MAIN_LINE, "audit start")
        for index in range(rounds):
            _pollute_round_state(med, clock.now())
            med.set_phase(Phase.STAGE_SELECT, f"audit round {index + 1} boundary")
            med.set_phase(Phase.MAIN_LINE, f"audit round {index + 1} start")

            for field, expected in clean_expected.items():
                observed = getattr(med, field)
                if observed != expected:
                    item = findings.setdefault(
                        field,
                        {
                            "field": field,
                            "scope": "ACTION_LOCAL" if field in {
                                "_choice_session",
                                "_pending_action",
                                "_pending_action_unconfirmed_count",
                                "_panel_pending_choice_action",
                                "_panel_pending_choice_fingerprint",
                                "_selection_repeat_key",
                                "_selection_repeat_attempts",
                            } else "ROUND_LOCAL",
                            "first_round": index + 1,
                            "expected": repr(expected),
                            "observed": repr(observed),
                            "rounds_affected": 0,
                        },
                    )
                    item["rounds_affected"] += 1

            for field, expected in session_expected.items():
                observed = getattr(med, field)
                if observed != expected:
                    item = findings.setdefault(
                        field,
                        {
                            "field": field,
                            "scope": "SESSION_GLOBAL",
                            "first_round": index + 1,
                            "expected": repr(expected),
                            "observed": repr(observed),
                            "rounds_affected": 0,
                        },
                    )
                    item["rounds_affected"] += 1

            frames.begin_tick(index)
            executor.begin_tick(index)
            actions.begin_tick(index)
            med.tick()
            input_records = executor.records_since_tick_start()
            semantic_actions = actions.records_since_tick_start()
            if (
                med._context_cache_value == "UNKNOWN"
                and not input_records
                and not semantic_actions
            ):
                unknown_zero_input_rounds += 1
            else:
                item = findings.setdefault(
                    "UNKNOWN_ZERO_INPUT",
                    {
                        "field": "UNKNOWN_ZERO_INPUT",
                        "scope": "ACTION_LOCAL",
                        "first_round": index + 1,
                        "expected": "context UNKNOWN and zero attempted input",
                        "observed": repr({
                            "context": med._context_cache_value,
                            "executor_methods": [record.method for record in input_records],
                            "semantic_actions": [asdict(record) for record in semantic_actions],
                        }),
                        "rounds_affected": 0,
                    },
                )
                item["rounds_affected"] += 1
            clock.advance(0.5)

    finding_rows = list(findings.values())
    return {
        "schema": "round-lifecycle-audit-v1",
        "status": "FAIL" if finding_rows else "PASS",
        "rounds": rounds,
        "production_class": "shuabao.runtime_mediator.Mediator",
        "input_boundary": "tests.test_scenario_replay.FakeInputExecutor",
        "real_input_calls": 0,
        "unknown_zero_input_rounds": unknown_zero_input_rounds,
        "session_global_preserved": not any(
            row["scope"] == "SESSION_GLOBAL" for row in finding_rows
        ),
        "production_defects": finding_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_audit(args.rounds)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
