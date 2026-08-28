"""Production Mediator extensions for round-local L1 completion guards.

The core Mediator deliberately keeps panel state generic. This runtime subclass
adds production-only liveness and post-action invariants for LIVE execution.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import time
from typing import Any

from shuabao.interaction_surface import PendingAction
from shuabao.log_sink import emit_print as print  # noqa: A001
from shuabao.loop_action import LoopAction
from shuabao.choice_policy import matches_bond_preset
from shuabao.mediator import Mediator as CoreMediator
from shuabao.mediator import PanelState, Phase
from shuabao.vision.matcher import MatchResult
from shuabao.vision.ocr_shadow.production import ProductionShadowClient
from shuabao.vision.stage_selector import configured_stage_id, selected_stage_row


class Mediator(CoreMediator):
    """Core Mediator plus production liveness/safety invariants."""

    _RUNTIME_STALL_TIMEOUT_S = 15.0
    _PANEL_FAIL_FORWARD_S = 3.0

    def __init__(self, settings, project_root, *args: Any, **kwargs: Any) -> None:
        self._bond_cards_pending: list[str] = []
        self._bond_cards_owned: list[str] = []
        self._physical_panel_signature: tuple[str, int] | None = None
        self._physical_panel_first_seen_at: float | None = None
        self._physical_panel_last_progress_at: float | None = None
        self._physical_panel_absent_since: float | None = None
        self._physical_panel_deadline_s: float = 30.0
        self._physical_panel_recoveries: int = 0
        self._ocr_bootstrap_health: dict[str, Any] | None = None
        self._ocr_runtime_init_error: str | None = None
        self._l1_cycle_index: int = 0
        self._runtime_panel_unknown_signature: tuple[str, int] | None = None
        self._runtime_panel_unknown_since: float | None = None
        self._last_runtime_progress_at: float = time.time()

        # Prevent the generic core constructor from creating a legacy-compatible
        # OCR client. LIVE replaces it with the ShuaBao-only production client
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
                # The desktop package currently ships the template matcher but
                # not the heavyweight Paddle sidecar.  Do not make an existing
                # user's old "live" preference turn the whole application into
                # an unstartable program.  In a frozen build only, downgrade to
                # the already-supported template-only policy.  That policy is
                # still fail-closed: cards without an exact template are never
                # clicked.  Source runs and any future package that includes the
                # sidecar retain their requested OCR mode.
                if (
                    getattr(sys, "frozen", False)
                    and "packaged OCR runtime missing" in self._ocr_runtime_init_error
                ):
                    settings.ocr_mode = "off"
                    self._ocr_bootstrap_health = {
                        "healthy": True,
                        "skipped": True,
                        "reason": "packaged_ocr_unavailable_template_mode",
                    }

        episode_deadline = float(getattr(self.settings, "panel_hard_deadline_s", 15.0) or 15.0)
        self._physical_panel_deadline_s = max(30.0, min(60.0, episode_deadline * 2.5))
        self._l1_cycle_index = 0
        self._last_runtime_progress_at = time.time()

    # ------------------------------------------------------------------
    # LIVE dependency bootstrap.
    # ------------------------------------------------------------------
    def prepare_live_dependencies(self) -> bool:
        """Prove OCR readiness before any LIVE business input can start."""
        mode = str(getattr(self.settings, "ocr_mode", "off") or "off").lower()
        if mode not in {"live", "shadow"}:
            if self._ocr_bootstrap_health is None:
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
    # Runtime progress / cycle traversal.
    # ------------------------------------------------------------------
    def _mark_runtime_progress(self, now: float | None = None) -> None:
        self._last_runtime_progress_at = float(now if now is not None else time.time())

    def _advance_l1_cycle(self, completed: str | None = None) -> None:
        """Advance by position, not tuple.index(), so duplicate bond/skill steps work."""
        order = self._L1_CYCLE_ORDER
        current = completed or getattr(self, "_l1_cycle_step", order[0])
        idx = int(getattr(self, "_l1_cycle_index", 0) or 0)
        if not (0 <= idx < len(order) and order[idx] == current):
            matches = [i for i, step in enumerate(order) if step == current]
            if matches:
                forward = [i for i in matches if i >= idx]
                idx = forward[0] if forward else matches[0]
            else:
                idx = -1
        next_idx = (idx + 1) % len(order)
        nxt = order[next_idx]
        if nxt == "evolve":
            self._evolve_ok_this_cycle = False
            self._evolve_awaiting_hero_pick = False
        if nxt == "equipment" or completed == "evolve":
            self._inventory_clicks_this_visit = 0
            self._inventory_last_pt = None
            self._inventory_same_pt_hits = 0
            self._inventory_next_at = 0.0
            self._devour_dan_consecutive_clicks = 0
        self._l1_cycle_index = next_idx
        self._l1_cycle_step = nxt

    def _runtime_watchdog_allowed(self, now: float) -> bool:
        if getattr(self, "phase", None) != Phase.MAIN_LINE:
            return False
        if bool(getattr(self.settings, "dry_run", False)):
            return False
        if getattr(self, "_post_game_pending", False):
            return False
        if getattr(self, "_panel_state", PanelState.CLOSED) != PanelState.CLOSED:
            return False
        pending = getattr(self, "_pending_action", None)
        if pending is not None and now < float(getattr(pending, "deadline", 0.0) or 0.0):
            return False
        started = getattr(self, "_main_line_started_at", None)
        if (
            started is not None
            and now - started < 20.0
            and bool(getattr(self.settings, "pre_wave_protection", False))
            and not bool(getattr(self.settings, "skip_pre_wave_delay", False))
        ):
            self._mark_runtime_progress(now)
            return False
        return True

    def _tick_main_line(self, frame):
        now = time.time()
        if self._runtime_watchdog_allowed(now):
            stagnant_for = now - float(getattr(self, "_last_runtime_progress_at", now) or now)
            if stagnant_for >= self._RUNTIME_STALL_TIMEOUT_S:
                print(
                    f"[med] LIVE 活性看门狗：{stagnant_for:.1f}s 无真实输入/确认进展，"
                    "ESC 脱困并推进主循环"
                )
                self.act_key("escape", "RuntimeWatchdog-EscUnstuck")
                self._advance_l1_cycle()
                self._main_line_since = now
                self._mark_runtime_progress(now)
                return LoopAction.Continue
        return super()._tick_main_line(frame)

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
        self._runtime_panel_unknown_signature = None
        self._runtime_panel_unknown_since = None

    def _verified_panel_close(self, frame, kind: str | None) -> MatchResult | None:
        if kind == "skill":
            names = ["skill_hide", "card_hide", "hide"]
        elif kind == "treasure":
            names = ["card_hide", "treasure_hide_btn", "skill_hide", "hide"]
        elif kind in ("bond", "card"):
            names = ["card_hide", "bond_hide_btn", "skill_hide", "hide"]
        else:
            names = ["skill_hide", "card_hide", "bond_hide_btn", "treasure_hide_btn", "hide"]
        threshold = max(0.65, float(getattr(self.settings, "match_threshold", 0.75) or 0.75))
        hit = self.find(
            frame,
            names,
            threshold=threshold,
            scales=self._hot_scales(),
            roi=self._PANEL_BUTTONS_ROI,
            early_stop=True,
        )
        if hit is None:
            hit = self.find(
                frame,
                names,
                threshold=threshold,
                scales=self._wide_scales(),
                roi=self._PANEL_BUTTONS_ROI,
                early_stop=True,
            )
        return hit

    def _hide_fallback_hit(self, frame, kind: str | None = None) -> None:
        """LIVE forbids unverified fixed-coordinate panel-close clicks."""
        return None

    def _arm_runtime_unknown_panel(self, frame, kind: str) -> None:
        signature = (str(kind or "unknown"), int(getattr(frame, "hwnd", 0) or 0))
        if signature != self._runtime_panel_unknown_signature:
            self._runtime_panel_unknown_signature = signature
            self._runtime_panel_unknown_since = time.time()

    def _clear_runtime_unknown_panel(self) -> None:
        self._runtime_panel_unknown_signature = None
        self._runtime_panel_unknown_since = None

    def _panel_fail_forward(self, frame, anchor, now: float) -> LoopAction:
        # 20260822：删除 3s 品质盲选（FailForward-Rarity）——实机与用户反馈均
        # 证实盲选=乱拿（宝物"选蓝不选紫"同源）。Fail-Forward 只走已验证
        # 关闭锚点 → ESC → Fail-Closed 的安全链。
        kind = self._panel_kind_of(frame, anchor) if anchor is not None else str(getattr(self, "_panel_kind", "unknown"))
        close_hit = self._verified_panel_close(frame, kind)
        if close_hit is not None and self.act_click(close_hit, "PanelFailForward-VerifiedClose"):
            self._bump_choice_attempts()
            self._panel_executed_actions += 1
            self._panel_last_progress_at = now
            self._stage_panel_choice_action("close", (kind, close_hit.name))
            self._panel_state = PanelState.WAIT_MUTATION
            self._panel_mutation_baseline = self._panel_roi_region(frame)
            self._panel_last_input_at = now
            self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
            self._clear_runtime_unknown_panel()
            print(f"[L1] Fail-Forward：品质不可判，点击已验证关闭锚点 {close_hit.name}")
            return LoopAction.Continue

        if self.act_key("escape", "PanelFailForward-Esc"):
            self._panel_state = PanelState.WAIT_MUTATION
            self._panel_mutation_baseline = self._panel_roi_region(frame)
            self._panel_last_input_at = now
            self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
            self._clear_runtime_unknown_panel()
            print("[L1] Fail-Forward：无可信卡/关闭锚点，发送 ESC 并等待画面确认")
            return LoopAction.Continue

        print("[L1] Fail-Forward：ESC 被输入门禁拒绝，同一物理面板无法恢复，Fail-Closed 停止运行")
        self.set_phase(Phase.ERROR, "physical panel fail-forward exhausted")
        self.stop()
        return LoopAction.Break

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
            "physical_panel_stagnation_recovered: "
            f"kind={signature[0]} hwnd={signature[1]} "
            f"stagnant_for={stagnant_for:.2f}s deadline={self._physical_panel_deadline_s:.2f}s"
        )
        self._record_fail_closed_incident(note)
        self._physical_panel_recoveries += 1
        self._physical_panel_last_progress_at = now
        print(
            f"[L1] 同一物理选择面板无确认进展 {stagnant_for:.1f}s，"
            f"执行第 {self._physical_panel_recoveries} 次 Fail-Forward 恢复，不停止脚本"
        )
        return self._panel_fail_forward(frame, anchor, now)

    def _tick_panel_fsm(self, frame, anchor, now: float):
        guard = self._physical_panel_watchdog(frame, anchor, now)
        if guard is not None:
            return guard
        if (
            getattr(self, "_panel_state", PanelState.CLOSED) == PanelState.ACTIVE
            and anchor is not None
            and self._runtime_panel_unknown_since is not None
            and now - self._runtime_panel_unknown_since >= self._PANEL_FAIL_FORWARD_S
        ):
            return self._panel_fail_forward(frame, anchor, now)
        result = super()._tick_panel_fsm(frame, anchor, now)
        if anchor is None and getattr(self, "_panel_state", PanelState.CLOSED) in {PanelState.CLOSED, PanelState.COOLDOWN}:
            self._clear_runtime_unknown_panel()
        return result

    def _confirm_panel_choice_action(self, now: float) -> None:
        super()._confirm_panel_choice_action(now)
        if self._physical_panel_signature is not None:
            self._physical_panel_last_progress_at = now
        self._clear_runtime_unknown_panel()
        self._mark_runtime_progress(now)

    # ------------------------------------------------------------------
    # Evolution: never treat refresh as a completed hero pick; 3-card fallback.
    # ------------------------------------------------------------------
    def _find_evolution_choice(self, frame, anchor=None):
        hit = super()._find_evolution_choice(frame, anchor)
        if hit is not None and "refresh" not in str(getattr(hit, "name", "")).lower():
            return hit
        # 20260822（trace 181735 18:19:41-45 连点 9 次）：_rarity_choice 兜底
        # 绝不能在已定性为 skill/bond/treasure/card 的选择面板上触发——
        # 那会把普通三选一当成进化弹窗盲点（宝物"选蓝不选紫"的根因）。
        if (
            getattr(self, "_evolve_awaiting_hero_pick", False)
            and getattr(self, "_panel_opened_by_us", None) is None
            and getattr(self, "_panel_state", PanelState.CLOSED) == PanelState.CLOSED
            and self._classify_choice_panel(frame) is None
        ):
            fallback = self._rarity_choice(frame, "card") or self._rarity_choice(frame, "skill")
            if fallback is not None:
                return fallback
        return None

    # ------------------------------------------------------------------
    # Inventory/equipment: no-op inventory checks must not swallow equipment.
    # ------------------------------------------------------------------
    def _maybe_use_inventory_item(self, frame):
        pending = getattr(self, "_pending_action", None)
        now = time.time()
        if pending is not None and not pending.is_confirmed(frame) and now < pending.deadline:
            return LoopAction.Continue
        if self._black_merchant_present(frame) or self._panel_state != PanelState.CLOSED:
            return None

        inventory_roi = (0.64, 0.77, 0.74, 0.98)
        if self.settings.auto_devour_dan and self._bond_bar_nonempty(frame):
            pill = self.find(
                frame,
                ["danGif"],
                threshold=0.55,
                scales=self._hot_scales(),
                roi=inventory_roi,
            )
            if pill is not None and now >= self._devour_dan_next_at and self._devour_dan_consecutive_clicks < 5:
                baseline_occ = getattr(self, "_bond_bar_occupancy", lambda f: None)(frame)
                if self.act_click(pill, "UseInventory-swallow_pill"):
                    self._devour_dan_next_at = now + 1.0
                    self._devour_dan_consecutive_clicks += 1
                    self._inventory_next_at = now + 1.0
                    self._pending_action = PendingAction(
                        kind="WAIT_DEVOUR_DAN",
                        target_id="danGif",
                        deadline=now + 2.0,
                        verifier=lambda f: bool(
                            (
                                baseline_occ is not None
                                and getattr(self, "_bond_bar_occupancy", lambda _: None)(f) is not None
                                and getattr(self, "_bond_bar_occupancy", lambda _: None)(f) < baseline_occ
                            )
                            or (not self._bond_bar_nonempty(f))
                            or (
                                self.find(
                                    f,
                                    ["danGif"],
                                    threshold=0.55,
                                    scales=self._hot_scales(),
                                    roi=inventory_roi,
                                )
                                is None
                            )
                        ),
                    )
                    return LoopAction.Continue
            elif pill is None:
                self._devour_dan_consecutive_clicks = 0

        if not getattr(self, "_evolve_ok_this_cycle", False):
            return None
        if now < self._inventory_next_at or self._inventory_clicks_this_visit >= 2:
            return None
        hero_card = self.find(
            frame,
            ["hero_card_item"],
            threshold=0.70,
            roi=inventory_roi,
            scales=(0.8, 0.9, 1.0, 1.1, 1.2),
        )
        if hero_card is None:
            return None
        if not self.act_click(hero_card, "UseInventory-hero-card"):
            return None
        self._inventory_clicks_this_visit += 1
        self._inventory_next_at = now + 1.0
        self._evolve_awaiting_hero_pick = True
        self._pending_action = PendingAction(
            kind="WAIT_HERO_CHOICE",
            target_id="hero_card_item",
            deadline=now + 3.0,
            verifier=lambda f: bool(self._find_evolution_choice(f) is not None),
        )
        print(f"[L1] 使用背包英雄卡 @ {hero_card.center}")
        return LoopAction.Continue

    # ------------------------------------------------------------------
    # Merchant: swallow pill remains independent; refresh obeys user opt-in.
    # ------------------------------------------------------------------
    def _maybe_black_merchant(self, frame):
        if bool(getattr(self.settings, "auto_gambling", False)):
            return super()._maybe_black_merchant(frame)
        now = time.time()
        if now < self._merchant_next_at or not self._black_merchant_present(frame):
            return None
        if not bool(getattr(self.settings, "auto_devour_dan", True)) or not self._bond_bar_nonempty(frame):
            return None
        pill = self.find(
            frame,
            ["danGif"],
            threshold=0.50,
            scales=(0.5, 0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5),
            roi=(0.70, 0.66, 0.90, 0.76),
        )
        if not self._in_merchant_strip(frame, pill):
            return None
        hit = self._hud_button_hit(
            frame,
            "black_merchant_swallow_pill",
            (pill.x / frame.width, pill.y / frame.height),
        )
        if self.act_click(hit, "BlackMerchant-swallow_pill"):
            self._merchant_next_at = now + max(1.2, float(self.settings.ui_action_interval_s))
            return LoopAction.Continue
        return None

    # ------------------------------------------------------------------
    # Stage selection: SendInput success alone is not selection proof.
    # ------------------------------------------------------------------
    def _find_stage_start(self, frame):
        hit = super()._find_stage_start(frame)
        if hit is None or not getattr(self, "_stage_selected", False):
            return hit
        wanted = configured_stage_id(
            self.settings.stage_targets,
            self.settings.stage1,
            self.settings.stage2,
        )
        highlighted = selected_stage_row(frame, self.images)
        if wanted is None or highlighted is None or highlighted.stage_id != wanted:
            print("[L0] 目标关卡缺少正向高亮确认，重新点选目标行，不启动旧关卡")
            self._stage_selected = False
            self._stage_target_name = None
            self._stage_target_position = None
            self._stage_candidate_name = None
            self._stage_candidate_position = None
            self._stage_candidate_frames = 0
            return None
        return hit

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
        # Bond cards can repeat for upgrades/combines, so the configured
        # whitelist remains active throughout a round.
        return self._configured_bond_presets()

    def _bond_presets_complete(self) -> bool:
        return not self._configured_bond_presets()

    def _stage_bond_card(self, name: str | None) -> None:
        canonical = self._canonical_bond_name(name)
        configured = self._configured_bond_presets()
        if not matches_bond_preset(canonical, configured):
            return
        # 重复卡必须保留次数，供“已拿卡优先合成”决策使用。
        self._bond_cards_pending.append(canonical)

    def _commit_pending_bond_cards(self) -> None:
        if not self._bond_cards_pending:
            return
        for name in self._bond_cards_pending:
            self._bond_cards_owned.append(name)
            print(f"[L1] 羁绊确认获得：{name}；当前持有次数={self._bond_cards_owned.count(name)}")
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
        if clicked:
            self._mark_runtime_progress()
        if (
            clicked
            and getattr(self, "_panel_kind", None) == "bond"
            and reason == "bond选择"
            and self._is_bond_card_click_name(getattr(hit, "name", None))
        ):
            self._stage_bond_card(getattr(hit, "name", None))
        return clicked

    def act_right_click(self, hit: MatchResult, reason: str = "", *args: Any, **kwargs: Any) -> bool:
        clicked = super().act_right_click(hit, reason, *args, **kwargs)
        if clicked:
            self._mark_runtime_progress()
        return clicked

    def act_key(self, key: str, reason: str = "", *args: Any, **kwargs: Any) -> bool:
        pressed = super().act_key(key, reason, *args, **kwargs)
        if pressed:
            self._mark_runtime_progress()
        return pressed

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
            self._l1_cycle_index = 0
            self._mark_runtime_progress()

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
            self._clear_runtime_unknown_panel()
            return None

        kind = self._panel_kind_of(frame, anchor)
        if kind == "bond" and self._bond_presets_complete():
            close_hit = self._verified_panel_close(frame, "bond")
            if close_hit is not None:
                self._clear_runtime_unknown_panel()
                print("[L1] 羁绊预设已完成：关闭当前羁绊面板，不再选卡/刷新")
                return ("bond", close_hit)
            self._choice_policy_idle = True
            self._choice_policy_last_reason = "羁绊预设已完成但当前帧无已验证关闭按钮"
            self._arm_runtime_unknown_panel(frame, kind)
        result = super()._find_reward_choice(frame, anchor=anchor)
        if result is None:
            self._arm_runtime_unknown_panel(frame, kind)
            return None

        self._clear_runtime_unknown_panel()
        if kind != "bond":
            return result

        label, hit = result
        hit_name = getattr(hit, "name", "")
        if not self._is_bond_card_click_name(hit_name):
            return result

        # 非预设羁绊否决只对硬禁用模式生效；soft 模式保留策略结果。
        if str(getattr(self.settings, "bond_whitelist_mode", "soft") or "soft") != "hard":
            return result

        canonical = self._canonical_bond_name(hit_name)
        remaining = set(self._remaining_bond_presets())
        if matches_bond_preset(canonical, tuple(remaining)):
            return result

        close_hit = self._verified_panel_close(frame, "bond")
        if close_hit is not None:
            return ("bond", close_hit)
        self._choice_policy_idle = True
        self._choice_policy_last_reason = "羁绊仅出现已确认预设，等待 Fail-Forward 收口"
        self._arm_runtime_unknown_panel(frame, kind)
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
                "physical_panel_recoveries": self._physical_panel_recoveries,
                "runtime_panel_unknown_since": self._runtime_panel_unknown_since,
                "last_runtime_progress_at": self._last_runtime_progress_at,
                "l1_cycle_index": self._l1_cycle_index,
                "ocr_bootstrap_health": self._ocr_bootstrap_health,
            }
        )
        return data
