"""Test helpers and fixtures for runtime_core_adapter test suite."""
from __future__ import annotations

from dataclasses import replace
import numpy as np

from shuabao.interaction_surface import InteractionSurface, PendingAction
from shuabao.mediator import FrameEvidence, PanelState
from shuabao.runtime_core.arbiter import Decision, Demand, Grant
from shuabao.runtime_core.coordinator import ActionContract, Coordinator
from shuabao.runtime_core.transactions import Proof
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult
from shuabao.runtime_core_adapter import (
    Fact,
    Knowledge,
    PendingObservation,
    TargetObservation,
    WindowEpochParts,
    WorldSnapshot,
)


def make_frame(
    bgr: np.ndarray | None = None,
    hwnd: int | None = 1001,
    is_valid: bool = True,
    is_minimized: bool = False,
    timestamp: float = 100.0,
    role: str | None = "game",
    left: int = 0,
    top: int = 0,
    error: str | None = None,
) -> Frame:
    if bgr is None and is_valid:
        bgr = np.ones((100, 100, 3), dtype=np.uint8) * 128
    return Frame(
        bgr=bgr,  # type: ignore
        left=left,
        top=top,
        window_title="Heroes of Three Kingdoms",
        hwnd=hwnd,
        timestamp=timestamp,
        is_valid=is_valid,
        error=error,
        role=role,
        is_minimized=is_minimized,
    )


def make_epoch_parts(
    schema_version: int = 1,
    window_binding_id: str = "binding:1",
    hwnd: int = 1001,
    process_identity: str = "pid:1234:1",
    window_role: str = "game",
    client_size: tuple[int, int] = (1920, 1080),
    dpi: int = 96,
    ui_scale: float = 1.0,
    layout_version: str = "v1",
) -> WindowEpochParts:
    return WindowEpochParts(
        schema_version=schema_version,
        window_binding_id=window_binding_id,
        hwnd=hwnd,
        process_identity=process_identity,
        window_role=window_role,
        client_size=client_size,
        dpi=dpi,
        ui_scale=ui_scale,
        layout_version=layout_version,
    )


def make_evidence(
    frame: Frame,
    gen: int = 1,
    ui_scale: float = 1.0,
    hwnd: int | None = 1001,
) -> FrameEvidence:
    return FrameEvidence(
        frame_ref=frame,
        gen=gen,
        ui_scale=ui_scale,
        hwnd=hwnd,
    )


def make_proof(
    gen: int = 1,
    now: float = 0.0,
    epoch: str = "epoch:1",
    valid: bool = True,
    postcondition: bool | None = None,
    cursor_empty: bool | None = True,
    surface_released: bool | None = True,
    **kwargs,
) -> Proof:
    fields = dict(
        generation=gen,
        captured_at=now,
        epoch=epoch,
        valid=valid,
        postcondition=postcondition,
        cursor_empty=cursor_empty,
        surface_released=surface_released,
    )
    fields.update(kwargs)
    return Proof(**fields)


def make_snapshot(
    round_id: str = "round:1",
    generation: int = 1,
    observed_at: float = 0.0,
    epoch: str = "epoch:1",
    frame_healthy: Fact[bool] | None = None,
    window_role: Fact[str] | None = None,
    interaction_surface: Fact[str] | None = None,
    panel_state: Fact[str] | None = None,
    input_safe: Fact[bool] | None = None,
    cursor_empty: Fact[bool] | None = None,
    surface_released: Fact[bool] | None = None,
    pending_action: Fact[PendingObservation] | None = None,
    targets: tuple[TargetObservation, ...] = (),
    task_facts: dict[str, Fact[object]] | None = None,
) -> WorldSnapshot:
    return WorldSnapshot(
        round_id=round_id,
        generation=generation,
        observed_at=observed_at,
        epoch=epoch,
        frame_healthy=frame_healthy or Fact(Knowledge.KNOWN, True, "capture", "v1"),
        window_role=window_role or Fact(Knowledge.KNOWN, "game", "window", "v1"),
        interaction_surface=interaction_surface or Fact(Knowledge.KNOWN, "HUD_ONLY", "surface", "v1"),
        panel_state=panel_state or Fact(Knowledge.KNOWN, "CLOSED", "fsm", "v1"),
        input_safe=input_safe or Fact(Knowledge.KNOWN, True, "safety", "v1"),
        cursor_empty=cursor_empty or Fact(Knowledge.KNOWN, True, "cursor", "v1"),
        surface_released=surface_released or Fact(Knowledge.KNOWN, True, "surface", "v1"),
        pending_action=pending_action or Fact(Knowledge.KNOWN, None, "pending", "v1"),
        targets=targets,
        task_facts=task_facts or {},
    )


class DummyAuthorizer:
    def __init__(self, allowed_tasks: set[str] | None = None) -> None:
        self.allowed_tasks = allowed_tasks if allowed_tasks is not None else {"skill", "bond", "treasure", "pickup"}

    def authorize(self, grant: Grant, snapshot: WorldSnapshot) -> ActionContract | None:
        if grant.task not in self.allowed_tasks:
            return None
        # Check if targets or domain facts are unknown
        for t in snapshot.targets:
            if t.machine_id.knowledge == Knowledge.UNKNOWN:
                return None
        return ActionContract(
            action_id=f"act:{grant.task}",
            target_id=f"tgt:{grant.task}",
            postcondition_id=f"post:{grant.task}",
            authorized=True,
        )
