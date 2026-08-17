"""只读 RuntimeStatus。从 mediator 字段快照，不改决策、不调用输入。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


def _recovery_step(med: Any) -> str | None:
    state = getattr(med, "_recovery_state", None)
    if state is not None:
        step = getattr(state, "step", None)
        name = _enum_name(step)
        if name:
            return name
    return getattr(med, "_recovery_step", None)


def _recovery_kind(med: Any) -> str | None:
    state = getattr(med, "_recovery_state", None)
    if state is None:
        return None
    return _enum_name(getattr(state, "kind", None))


@dataclass(frozen=True)
class RuntimeStatus:
    tick: int
    ts: float
    phase: str
    phase_before: str
    run_mode: str
    interrupt_reason: str | None
    context: str | None
    hwnd: int | None
    size: tuple[int, int] | None
    actions: tuple
    controls: tuple
    scenes: tuple
    reason: str | None
    evidence_gen: int | None
    settings_summary: dict
    panel: tuple
    ocr_suggestion: dict | None
    decision: str | None
    post_confirm: bool | None
    s0: dict
    lab_focus: str
    dry_run: bool


def runtime_status_from_mediator(med: Any) -> RuntimeStatus:
    """纯函数快照。只读 getattr，不写 med 字段，不调 act_click / _tick_*。"""
    frame = getattr(med, "_last_frame", None)
    settings = getattr(med, "settings", None)
    phase = getattr(med, "phase", None)
    phase_name = _enum_name(phase) or ""
    actions = tuple(getattr(med, "_trace_actions", None) or ())
    interrupt = getattr(med, "_interrupt_reason", None)
    decision = None
    if interrupt:
        decision = f"error:{interrupt}"
    elif actions and isinstance(actions[-1], dict) and actions[-1].get("reason"):
        decision = f"act:{actions[-1]['reason']}"
    post_confirm = True if getattr(med, "_recovery_step", None) == "DONE" else None
    size = None
    hwnd = None
    if frame is not None:
        hwnd = getattr(frame, "hwnd", None)
        width = getattr(frame, "width", None)
        height = getattr(frame, "height", None)
        if width and height:
            size = (int(width), int(height))
    dry_run = bool(getattr(settings, "dry_run", False)) if settings is not None else False
    lab_focus = str(getattr(settings, "lab_focus", "") or "") if settings is not None else ""
    scenes = tuple(getattr(med, "_trace_scenes", None) or ())
    panel = tuple(
        {"name": s.get("name"), "score": s.get("score")}
        for s in sorted(scenes, key=lambda row: row.get("score", 0.0), reverse=True)[:3]
        if isinstance(s, dict)
    )
    evidence = getattr(med, "_evidence", None)
    return RuntimeStatus(
        tick=int(getattr(med, "_tick_no", 0) or 0),
        ts=0.0,
        phase=phase_name,
        phase_before=phase_name,
        run_mode="OBSERVE" if dry_run else "LIVE",
        interrupt_reason=interrupt,
        context=getattr(med, "_context_cache_value", None),
        hwnd=hwnd,
        size=size,
        actions=actions,
        controls=tuple(getattr(med, "_trace_controls", None) or ()),
        scenes=scenes,
        reason=getattr(med, "_tick_reason", None),
        evidence_gen=getattr(evidence, "gen", None) if evidence is not None else None,
        settings_summary={
            "ocr_mode": getattr(settings, "ocr_mode", "off") if settings is not None else "off",
            "lab_focus": lab_focus,
            "skills": list(getattr(settings, "skills", None) or []),
        },
        panel=panel,
        ocr_suggestion=getattr(med, "_trace_ocr_suggestion", None),
        decision=decision,
        post_confirm=post_confirm,
        s0={
            "round_deadline": getattr(med, "_round_deadline", None),
            "round_outcome": _enum_name(getattr(med, "_round_outcome", None)),
            "last_outcome": _enum_name(getattr(med, "_last_outcome", None)),
            "failure_streak": getattr(med, "_failure_streak", 0),
            "game_count": getattr(med, "game_count", 0),
            "panel_state": _enum_name(getattr(med, "_panel_state", None)),
            "recovery_step": _recovery_step(med),
            "recovery_kind": _recovery_kind(med),
            "f1_live": getattr(med, "_f1_live", False),
            "f1_shadow_correct": getattr(med, "_f1_shadow_correct", 0),
            "f1_shadow_misfire": getattr(med, "_f1_shadow_misfire", 0),
        },
        lab_focus=lab_focus,
        dry_run=dry_run,
    )
