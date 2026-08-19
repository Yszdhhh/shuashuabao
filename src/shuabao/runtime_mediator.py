"""Production Mediator extensions for round-local L1 completion guards.

The core Mediator deliberately keeps panel state generic.  This runtime
subclass adds the user-facing bond invariant without weakening the existing
post-click confirmation contract:

* Settings.cards is a name whitelist only; it has no target stack/count field.
  Therefore a preset is complete after one confirmed acquisition this round.
* A bond is only recorded after the core WAIT_MUTATION path confirms that the
  panel changed or closed.  Rejected clicks and confirmation timeouts never
  count as owned.
* Confirmed presets are removed from the remaining whitelist.  Once the list is
  empty, proactive F is skipped for the rest of the round and natural bond
  panels are closed instead of selecting/refreshing them.
* A physical choice panel also has a cross-episode liveness guard.  Core
  episode cooldowns may reset local counters, but a continuously visible panel
  cannot evade the runtime watchdog by being reopened as a fresh episode.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time
from typing import Any

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator as CoreMediator
from shuabao.mediator import PanelState, Phase
from shuabao.vision.matcher import MatchResult


class Mediator(CoreMediator):
    """Core Mediator plus verified runtime-only safety invariants."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Define overridable-hook state before super().__init__ in case future
        # core initialization calls a lifecycle method implemented here.
        self._bond_cards_pending: list[str] = []
        self._bond_cards_owned: list[str] = []
        self._physical_panel_signature: tuple[str, int] | None = None
        self._physical_panel_first_seen_at: float | None = None
        self._physical_panel_last_progress_at: float | None = None
        self._physical_panel_absent_since: float | None = None
        self._physical_panel_deadline_s: float = 30.0
        self._ocr_bootstrap_health: dict[str, Any] | None = None
        super().__init__(*args, **kwargs)
        episode_deadline = float(getattr(self.settings, "panel_hard_deadline_s", 15.0) or 15.0)
        # Long enough for one bounded episode + close/recovery, short enough to
        # prevent the same visible modal from cycling until the round deadline.
        self._physical_panel_deadline_s = max(30.0, min(60.0, episode_deadline * 2.5))

    # ------------------------------------------------------------------
    # LIVE dependency bootstrap.
    # ------------------------------------------------------------------
    def prepare_live_dependencies(self) -> bool:
        """Synchronously prove OCR readiness before LIVE business input starts.

        Desktop LIVE is configured for live OCR.  A spawned process is not
        enough: bootstrap must prove protocol readiness, a validated model,
        ping health, and a real warmup inference.  Failure is fail-closed and
        the caller must not start the automation loop.
        """
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
                "reason": "ocr_client_missing",
            }
            print("[ocr] LIVE bootstrap failed: OCR client was not created")
            return False

        timeout_ms = max(2000, min(10000, int(getattr(self.settings, "ocr_timeout_ms", 1500) or 1500) * 5))
        health = client.bootstrap(timeout_ms=timeout_ms)
        self._ocr_bootstrap_health = dict(health)
        if not bool(health.get("healthy")):
            print(
                "[ocr] LIVE bootstrap failed: "
                f"stage={health.get('stage')} reason={health.get('reason')} "
                f"python={client.python_executable} model_dir={client.model_dir}"
            )
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
                # Require sustained absence so a one-frame template miss does
                # not erase the history of a still-blocking physical modal.
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
        # Only a post-condition confirmation counts as real progress for the
        # cross-episode watchdog.  Merely sending another click does not.
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
        # Bypass this subclass' dynamic _policy_settings() so the configured
        # target set remains a stable source of truth for the whole round.
        return tuple(super()._policy_settings().bond_presets)

    def _remaining_bond_presets(self) -> tuple[str, ...]:
        owned = set(self._bond_cards_owned)
        return tuple(name for name in self._configured_bond_presets() if name not in owned)

    def _bond_presets_complete(self) -> bool:
        # Empty whitelist means the user requested no bond cards, so proactive F
        # should be skipped rather than opening an empty hard-whitelist panel.
        return not self._remaining_bond_presets()

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

    # The core already invokes these two hooks exactly at the safe boundaries:
    # WAIT_MUTATION confirmed -> commit; timeout/episode reset -> clear.
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
            # Stage only after the input executor accepted the click.  The core
            # mutation-confirmation path decides whether it becomes owned.
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
            self, "_l1_cycle_step", "skill"
        )
        if (
            target == "bond"
            and getattr(self, "_panel_state", PanelState.CLOSED) == PanelState.CLOSED
            and self._bond_presets_complete()
        ):
            self._panel_episode_count["bond"] = 0
            self._advance_l1_cycle("bond")
            print("[L1] 羁绊预设已全部确认拿齐，本局跳过 F 面板，转入宝物")
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
            # Do not fall through to generic bond refresh/selection if the panel
            # has no close affordance in the current frame.
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

        # Defensive guard for template/shadow fallback: never re-take an already
        # confirmed preset even if the generic fallback returns it first.
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
        """Propagate core diagnostics plus cross-episode physical-panel state."""
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
