"""Production Mediator extensions for round-local L1 completion guards.

The core Mediator deliberately keeps panel state generic.  This runtime
subclass adds verified production-only invariants for LIVE execution.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time
from typing import Any

from shuabao.log_sink import emit_print as print  # noqa: A001
from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator as CoreMediator
from shuabao.mediator import PanelState, Phase
from shuabao.vision.matcher import MatchResult
from shuabao.vision.ocr_shadow.production import ProductionShadowClient


class Mediator(CoreMediator):
    """Core Mediator plus verified runtime-only safety invariants."""

    def __init__(self, settings, project_root, *args: Any, **kwargs: Any) -> None:
        self._bond_cards_pending: list[str] = []
        self._bond_cards_owned: list[str] = []
        self._physical_panel_signature: tuple[str, int] | None = None
        self._physical_panel_first_seen_at: float | None = None
        self._physical_panel_last_progress_at: float | None = None
        self._physical_panel_absent_since: float | None = None
        self._physical_panel_deadline_s: float = 30.0
        self._ocr_bootstrap_health: dict[str, Any] | None = None
        self._ocr_runtime_init_error: str | None = None

        # Prevent the generic core constructor from creating a legacy-compatible
        # OCR client.  LIVE replaces it with the ShuaBao-only production client
        # immediately after core state is initialized.
        original_mode = str(getattr(settings, "ocr_mode", "off") or "off")
        had_enabled = hasattr(settings, "ocr_enabled")
        original_enabled = getattr(settings, "ocr_enabled", None)
        settings.ocr_mode = "off"
        if had_enabled:
            settings.ocr_enabled = False
        try:
            super().__init__(settings, project_root, *args, **kwargs)
        finally:
            settings.ocr_mode = original_mode
            if had_enabled:
                settings.ocr_enabled = original_enabled

        if original_mode.lower() in {"live", "shadow"}:
            trace_path = None
            incident_dir = kwargs.get("incident_dir")
            if incident_dir:
                trace_path = Path(incident_dir) / "ocr_shadow.jsonl"
            try:
                self._ocr_client = ProductionShadowClient(
                    repo_root=Path(project_root),
                    timeout_ms=int(getattr(settings, "ocr_timeout_ms", 1500) or 1500),
                    startup_timeout_ms=30000,
                    trace_path=trace_path,
                )
            except Exception as exc:
                self._ocr_client = None
                self._ocr_runtime_init_error = str(exc)

        episode_deadline = float(getattr(self.settings, "panel_hard_deadline_s", 15.0) or 15.0)
        self._physical_panel_deadline_s = max(30.0, min(60.0, episode_deadline * 2.5))

    # ------------------------------------------------------------------
    # LIVE dependency bootstrap.
    # ------------------------------------------------------------------
    def prepare_live_dependencies(self) -> bool:
        """Prove OCR readiness before any LIVE business input can start."""
        mode = str(getattr(self.settings, "ocr_mode", "off") or "off").lower()
        if mode not in {"live", "shadow"}:
            self._ocr_bootstrap_health = {
                "healthy": True,
                "skipped": True,
                "reason": "ocr_disabled",
            }
            return True

        client = getattr(self, "_ocr_client", None)
        if client is None:
            self._ocr_bootstrap_health = {
                "healthy": False,
                "stage": "client",
                "reason": self._ocr_runtime_init_error or "ocr_client_missing",
            }
            print(f"[ocr] LIVE bootstrap failed: {self._ocr_bootstrap_health}")
            return False

        timeout_ms = max(
            2000,
            min(10000, int(getattr(self.settings, "ocr_timeout_ms", 1500) or 1500) * 5),
        )
        started = time.perf_counter()

        if not client.start():
            self._ocr_bootstrap_health = {
                "healthy": False,
                "stage": "start",
                "reason": client.ready_reason or "start_failed",
                "model_validated": client.model_validated,
                "model_name": client.model_name,
                "model_hash": client.model_hash,
            }
            print(f"[ocr] LIVE bootstrap failed at start: {self._ocr_bootstrap_health}")
            client.close()
            return False

        if not client.ping(timeout_ms=timeout_ms):
            self._ocr_bootstrap_health = {
                "healthy": False,
                "stage": "ping",
                "reason": client.ready_reason or "ping_failed",
                "model_validated": client.model_validated,
                "model_name": client.model_name,
                "model_hash": client.model_hash,
            }
            print(f"[ocr] LIVE bootstrap failed at ping: {self._ocr_bootstrap_health}")
            client.close()
            return False

        warmup_started = time.perf_counter()
        if not client.warmup(timeout_ms=timeout_ms):
            self._ocr_bootstrap_health = {
                "healthy": False,
                "stage": "warmup",
                "reason": client.ready_reason or "warmup_failed",
                "model_validated": client.model_validated,
                "model_name": client.model_name,
                "model_hash": client.model_hash,
            }
            print(f"[ocr] LIVE bootstrap failed at warmup: {self._ocr_bootstrap_health}")
            client.close()
            return False
        warmup_ms = (time.perf_counter() - warmup_started) * 1000.0

        health = dict(client.health_check())
        health.update(
            {
                "stage": "ready",
                "reason": "ok" if health.get("healthy") else (health.get("ready_reason") or "health_failed"),
                "warmup_ms": round(warmup_ms, 1),
                "bootstrap_ms": round((time.perf_counter() - started) * 1000.0, 1),
            }
        )
        self._ocr_bootstrap_health = health
        if not bool(health.get("healthy")):
            print(f"[ocr] LIVE bootstrap health failed: {health}")
            client.close()
            return False

        print(
            "[ocr] LIVE READY "
            f"model={health.get('model_name')} hash={health.get('model_hash')} "
            f"load_ms={health.get('load_ms')} warmup_ms={health.get('warmup_ms')}"
        )
        return True

    # ------------------------------------------------------------------
    # Physical panel liveness across core episode resets.
    # ------------------------------------------------------------------
    def _physical_panel_key(self, frame, anchor) -> tuple[str, int]:
        kind = getattr(self, "_panel_kind", None)
        if not kind:
            try:
                kind = self._panel_kind_of(frame, anchor)
            except Exception:
                kind = str(getattr(anchor, "name", "unknown") or "unknown")
        return (str(kind or "unknown"), int(getattr(frame, "hwnd", 0) or 0))

    def _reset_physical_panel_guard(self) -> None:
        self._physical_panel_signature = None
        self._physical_panel_first_seen_at = None
        self._physical_panel_last_progress_at = None
        self._physical_panel_absent_since = None

    def _physical_panel_watchdog(self, frame, anchor, now: float) -> LoopAction | None:
        if anchor is None:
            if self._physical_panel_signature is None:
                return None
            if self._physical_panel_absent_since is None:
                self._physical_panel_absent_since = now
            elif now - self._physical_panel_absent_since >= 1.0:
                self._reset_physical_panel_guard()
            return None

        self._physical_panel_absent_since = None
        signature = self._physical_panel_key(frame, anchor)
        if signature != self._physical_panel_signature:
            self._physical_panel_signature = signature
            self._physical_panel_first_seen_at = now
            self._physical_panel_last_progress_at = now
            return None

        last_progress = self._physical_panel_last_progress_at or self._physical_panel_first_seen_at or now
        stagnant_for = max(0.0, now - last_progress)
        if stagnant_for < self._physical_panel_deadline_s:
            return None

        note = (
            "physical_panel_stagnation: "
            f"kind={signature[0]} hwnd={signature[1]} "
            f"stagnant_for={stagnant_for:.2f}s deadline={self._physical_panel_deadline_s:.2f}s"
        )
        print(f"[L1] 同一物理选择面板持续无确认进展 {stagnant_for:.1f}s，Fail-Closed 停止运行")
        self._record_fail_closed_incident(note)
        self.set_phase(Phase.ERROR, "persistent physical panel stagnation")
        self.stop()
        return LoopAction.Break

    def _tick_panel_fsm(self, frame, anchor, now: float):
        guard = self._physical_panel_watchdog(frame, anchor, now)
        if guard is not None:
            return guard
        return super()._tick_panel_fsm(frame, anchor, now)

    def _confirm_panel_choice_action(self, now: float) -> None:
        super()._confirm_panel_choice_action(now)
        if self._physical_panel_signature is not None:
            self._physical_panel_last_progress_at = now

    # ------------------------------------------------------------------
    # Bond facts: only post-click mutation confirmation grants ownership.
    # ------------------------------------------------------------------
    def _canonical_bond_name(self, name: str | None) -> str:
        text = str(name or "").strip()
        if not text:
            return ""
        if text.lower().startswith("ocr_bond:"):
            text = text.split(":", 1)[1].strip()
        stem = Path(text).stem
        return str(self._fetter_labels.get(stem, stem)).strip()

    @staticmethod
    def _is_bond_card_click_name(name: str | None) -> bool:
        text = str(name or "").lower()
        if not text:
            return False
        return not any(
            token in text
            for token in ("refresh", "giveup", "close", "hide", "lock", "button")
        )

    def _configured_bond_presets(self) -> tuple[str, ...]:
        return tuple(super()._policy_settings().bond_presets)

    def _remaining_bond_presets(self) -> tuple[str, ...]:
        # 羁绊卡在局内可重复获取（用于升级与合成），预设白名单持续生效
        return self._configured_bond_presets()

    def _bond_presets_complete(self) -> bool:
        return not self._configured_bond_presets()

    def _stage_bond_card(self, name: str | None) -> None:
        canonical = self._canonical_bond_name(name)
        configured = self._configured_bond_presets()
        if not canonical or canonical not in configured:
            return
        if canonical in self._bond_cards_owned or canonical in self._bond_cards_pending:
            return
        self._bond_cards_pending.append(canonical)

    def _commit_pending_bond_cards(self) -> None:
        if not self._bond_cards_pending:
            return
        for name in self._bond_cards_pending:
            if name not in self._bond_cards_owned:
                self._bond_cards_owned.append(name)
                print(f"[L1] 羁绊确认获得：{name}；剩余预设={self._remaining_bond_presets()}")
        self._bond_cards_pending.clear()

    def _clear_pending_bond_cards(self) -> None:
        self._bond_cards_pending.clear()

    def _confirmed_bond_cards(self) -> tuple[str, ...]:
        return tuple(self._bond_cards_owned)

    def _commit_pending_skill_cards(self) -> None:
        super()._commit_pending_skill_cards()
        self._commit_pending_bond_cards()

    def _clear_pending_skill_cards(self) -> None:
        super()._clear_pending_skill_cards()
        self._clear_pending_bond_cards()

    def act_click(self, hit: MatchResult, reason: str = "", *args: Any, **kwargs: Any) -> bool:
        clicked = super().act_click(hit, reason, *args, **kwargs)
        if (
            clicked
            and getattr(self, "_panel_kind", None) == "bond"
            and reason == "bond选择"
            and self._is_bond_card_click_name(getattr(hit, "name", None))
        ):
            self._stage_bond_card(getattr(hit, "name", None))
        return clicked

    # ------------------------------------------------------------------
    # Policy/runtime gating.
    # ------------------------------------------------------------------
    def _policy_settings(self):
        base = super()._policy_settings()
        remaining = self._remaining_bond_presets()
        if remaining == base.bond_presets:
            return base
        return replace(base, bond_presets=remaining)

    def set_phase(self, phase: Phase, note: str = "") -> None:
        previous = getattr(self, "phase", None)
        super().set_phase(phase, note)
        if phase == Phase.MAIN_LINE and previous != Phase.MAIN_LINE:
            self._bond_cards_pending.clear()
            self._bond_cards_owned.clear()
            self._reset_physical_panel_guard()

    def _maybe_open_choice_panel(self, frame, anchor=None):
        target = getattr(self, "_choice_target", None) or getattr(
            self, "_l1_cycle_step", "bond"
        )
        if (
            target == "bond"
            and getattr(self, "_panel_state", PanelState.CLOSED) == PanelState.CLOSED
            and self._bond_presets_complete()
        ):
            self._panel_episode_count["bond"] = 0
            self._advance_l1_cycle("bond")
            print("[L1] 羁绊预设已全部确认拿齐，本局跳过 F 面板，转入技能")
            return LoopAction.Continue
        return super()._maybe_open_choice_panel(frame, anchor=anchor)

    def _find_reward_choice(self, frame, anchor=None):
        if anchor is None:
            anchor = self._selection_anchor(frame)
        if not anchor:
            return None

        kind = self._panel_kind_of(frame, anchor)
        if kind == "bond" and self._bond_presets_complete():
            close_hit = self._close_current_panel(frame, "bond")
            if close_hit is not None:
                print("[L1] 羁绊预设已完成：关闭当前羁绊面板，不再选卡/刷新")
                return ("bond", close_hit)
            self._choice_policy_idle = True
            self._choice_policy_last_reason = "羁绊预设已完成但当前帧无可执行关闭按钮"
            return None

        result = super()._find_reward_choice(frame, anchor=anchor)
        if kind != "bond" or result is None:
            return result

        label, hit = result
        hit_name = getattr(hit, "name", "")
        if not self._is_bond_card_click_name(hit_name):
            return result

        canonical = self._canonical_bond_name(hit_name)
        remaining = set(self._remaining_bond_presets())
        if canonical in remaining:
            return result

        preferred = [v.strip() for v in self.settings.cards if v and v.strip()]
        eligible = [v for v in preferred if self._canonical_bond_name(v) in remaining]
        if eligible:
            names = [v if "/" in v else f"cards/{v}" for v in eligible]
            hits = self._match_all_preferred(frame, names, max_results=12)
            by_stem = {Path(candidate.name).stem: candidate for candidate in hits}
            for pref in eligible:
                candidate = by_stem.get(Path(pref).stem)
                if candidate is not None:
                    return ("bond", candidate)

        close_hit = self._close_current_panel(frame, "bond")
        if close_hit is not None:
            return ("bond", close_hit)
        self._choice_policy_idle = True
        self._choice_policy_last_reason = "羁绊仅出现已确认预设，等待后续帧关闭"
        return None

    def panel_episode_diagnostics(self) -> dict:
        data = super().panel_episode_diagnostics()
        now = time.time()
        data.update(
            {
                "physical_panel_signature": self._physical_panel_signature,
                "physical_panel_first_seen_at": self._physical_panel_first_seen_at,
                "physical_panel_last_progress_at": self._physical_panel_last_progress_at,
                "physical_panel_stagnant_s": (
                    max(0.0, now - self._physical_panel_last_progress_at)
                    if self._physical_panel_last_progress_at is not None
                    else 0.0
                ),
                "physical_panel_deadline_s": self._physical_panel_deadline_s,
                "ocr_bootstrap_health": self._ocr_bootstrap_health,
            }
        )
        return data
