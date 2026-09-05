# ShuaBao Architecture Stage 0 — Code Fact Audit

Date: 2026-09-04
Branch: `refactor/architecture-convergence-20260904`
Audit base: `59833447b40706c533b4caecddcb94c3ee32e9f1`
Remote observation: after `git fetch origin`, `origin/trial-merge` resolved to `bea21e509c5b175042e092af6199ac49c3b0d7f4`, not the user-specified `59833447b40706c533b4caecddcb94c3ee32e9f1`.
Governance sync: `bea21e509c5b175042e092af6199ac49c3b0d7f4` is the docs-only external-reference addendum; its content is synchronized onto this branch without production-code rework. Original audit and production baseline remain anchored at `59833447b40706c533b4caecddcb94c3ee32e9f1`.

## Scope and evidence method

This is a behavior-neutral audit. No production behavior was changed while collecting these facts. Sources:

- `docs/ARCHITECTURE_CONVERGENCE_20260904.md`
- `docs/LOCAL_AGENT_REFACTOR_HANDOFF_20260904.md`
- `docs/FABLE_EXTERNAL_REVIEW_NOTES_20260904.md`
- `docs/LOCAL_AGENT_EXTERNAL_REFERENCE_ADDENDUM_20260904.md`
- production code under `src/shuabao`
- focused source/consumer searches and existing tests
- baseline command run from this worktree:
  - `python -m pytest tests -q --tb=short` → `1431 passed, 13 skipped, 2 xfailed, 2 warnings`
  - `python tools/release_gate.py` → `4/4 PASS`; frozen replay retained existing `disconnect_modal_missing: BLOCKED`

The audit distinguishes direct OCR backend calls from dispatchers and pure text helpers. A `shadow_predict` transport call has no business classification until its caller consumes the response.

---

## 1. OCR usage map

### 1.1 Exhaustive direct production OCR call sites

There are six direct production `shadow_predict` call sites in `src/shuabao/mediator.py`. All six are below. `_ocr_reward_choice`, `_find_reward_choice`, `ShadowClient.shadow_predict`, the module-level `shadow_predict` facade, and `classify_hitch_ocr` are not additional direct production OCR call sites.

| File/function/line | ROI and request | Classification | Return consumption / Policy effect | Cheaper verifier possibility | GT required before change |
|---|---|---|---|---|---|
| `mediator.py:_ocr_panel_slots` L2306 | `_OCR_SLOT_ROIS` or `_OCR_SLOT_ROIS_4`, normalized to the current frame; `kind` is `skill`, `bond`, or `treasure` | `CATEGORY` | Candidate name/confidence/raw text becomes slot data, then `_slots_to_candidates` and `choice_policy.choose_action`; name/category changes selection, refresh, close, or zero-input policy | Existing finite lexicon/template/rarity evidence may replace some cases, but only with panel fixtures showing no wrong positive and no unacceptable UNKNOWN | Existing card/panel fixture corpus, especially ambiguous OCR and unknown-name fixtures; preserve `choice_policy` regression set |
| `mediator.py:_ocr_panel_slots` L2388 | Treasure description line ROI from `_OCR_DESC_ROIS`/`_OCR_DESC_ROIS_4`, same panel frame | `CATEGORY` | Raw text is accepted only with score/text gates and accumulated in `slot["description"]`; `choice_policy.is_negative_treasure` and `_drop_negative_treasures` use the semantic result | Finite negative-keyword/marker verifier or color/geometry only if real fixtures prove it answers the same semantic question | Existing treasure-description fixtures, including clipped/right-edge text and negative treasure cases |
| `mediator.py:_ocr_panel_slots` L2414 | One bounded wider retry for the same treasure-description line; width expands by about 0.2% | `CATEGORY` | Same description category as L2388; only materially more complete/high-score text replaces the narrow result | Keep as a bounded preprocess retry unless fixture A/B proves a simpler fixed ROI is equivalent | Existing clipped description fixtures and wrong-positive negative-description fixtures |
| `mediator.py:_merchant_discount_slots` L4022 | Fixed badge panel `(1150/1600,617/900,1410/1600,640/900)` and five slot ROIs, current-frame normalized | `VALUE_TYPED` | Raw/candidate text normalized by `_normalize_merchant_discount`, then regex matches finite `DISCOUNT_KEYWORDS` (`2折`/`5折`); produces `MerchantSlotItem`, and `merchant_scanner.rank_purchases` gives discount priority 1 | A finite glyph/shape/color verifier is plausible; do not replace until 2/5-fold GT demonstrates equivalent safety | Merchant discount fixtures for 2折, 5折, 8折/ordinary/no-label and OCR confusion cases |
| `mediator.py:_team_post_game_player_left` L6689 | Normalized chat ROI `(0.25,0.58,0.75,0.74)`, request kind `text`, session `post_game` | `EXPECTED_VALUE` | Whitespace-stripped raw text is checked for one of four leave markers; `_team_exit_ocr_hits >= 2` causes victory outcome and `QUIT` transition | Finite marker template/anchor could be cheaper, but chat text is dynamic enough that GT must prove recall and wrong-positive behavior | Team post-game real captures/fixtures with leave marker, unrelated chat, partial marker, and empty OCR |
| `mediator.py:_hitch_search_prefix_confirmed` L7095 | Search box ROI `(0.82,0.26,0.97,0.32)`, request kind `text`, session `lobby_hitch` | `EXPECTED_VALUE` | `has_prefix_evidence(raw_text,prefix)` gates `_hitch_prefix_searched`; filtered room rows are not inspected/joined until this succeeds | Small expected-glyph verifier for the configured prefix is the strongest candidate; a template alone cannot prove typed arbitrary prefix unless prefix set remains finite | Existing lobby search fixtures and any real capture set for configured `3`/`4` prefixes; wrong prefix must block join |

### 1.2 Non-call-site OCR-related code

| Code | Status | Fact |
|---|---|---|
| `mediator.py:_ocr_reward_choice` L2981 and `_find_reward_choice` L3141-L3163 | Dispatcher/consumer | Live mode dispatches panel OCR for `skill`/`bond`/`treasure`; `card` is not sent through this OCR condition. It is not an independent OCR call site. |
| `lobby_hitch.py:classify_hitch_ocr` L46-L51 | Category helper | Pure marker matching. In the live path it receives `_hitch_ocr_override`; `_hitch_ocr_text` L7064-L7077 is visual row/lobby logic and is not OCR. |
| `runtime_mediator.py:prepare_live_dependencies` L95-L199 | Lifecycle health probe, closest to `DISPLAY_DEBUG_ONLY` | Calls client start/health/ping/warmup. It does not produce a business value. It is not merely UI debug: failure blocks LIVE startup in `shell/live_execute.py` L362-L369. |
| `vision/ocr_shadow/worker.py:_predict` L127-L163 and warmup L294 | Shared backend | `kind` is caller-provided; no independent business semantics. Warmup uses `kind=None`. |

**Taxonomy conclusion:** no production business OCR call currently requires unconstrained `VALUE_OPEN`. The prior hypothesis of a post-game open chat OCR call is false: only the finite leave-marker consumer above exists. All business OCR is finite category, typed discount, or expected-value confirmation.

---

## 2. Retry / cooldown / timer / cached-target scope and reset map

### 2.1 Confirmed intended scopes and resets

| State | Intended scope | Actual reset/evolution | Finding |
|---|---|---|---|
| `_hitch_search_pending` | Search step/scene | Set after input L7459-L7461; cleared on OCR confirmation L7431-L7434 or 3s expiry L7436-L7440; `_hitch_after_exit` clears L7191-L7196 | Correctly bounded; no confirmed cross-scene leak |
| `_hitch_rejected_row_ys` | Current search result scene | Cleared after prefix confirmation and `_hitch_after_exit`; populated after rejected join | Correct scene-local behavior |
| `_hitch_blacklisted_room_keys` | Whole hitch session | Populated for rejected room keys; no automatic reset | Deliberate session blacklist, bounded by room-key representation; not a transient timer |
| `_hitch_floor_exit_pending`, `_hitch_floor_exit_confirmed` | Hitch room-exit scene | Set around L7300-L7306/L7373-L7375; cleared only when the flow observes no longer in room at L7351-L7353 | **Leak risk:** `_hitch_after_exit` L7187-L7196 does not clear these dynamic flags. A phase/event reset that calls `_hitch_after_exit` while still classified as in-room can retain the exit latch. |
| `_team_exit_ocr_next_at`, `_team_exit_ocr_hits` | Team post-game scene | OCR cadence L6681-L6683; hit count increments/resets L6703-L6707; `_team_exit_ocr_hits` is reset on MAIN_LINE entry L6062-L6064 | Intended scene/round reset present |
| `_choice_session` and `_skill_refresh_attempts` | Panel episode/step | `_reset_choice_session` L2673-L2680; panel entry/exit paths reset refresh state L9000-L9041 and related paths | Existing action/policy session is already the reset owner |
| `_stage_*` targets/cooldowns/attempts | Stage-select scene/step | `set_phase(STAGE_SELECT)` resets scroll/world/target/candidate/attempt fields L5926-L5938; page-tab flow also clears target/candidate and scroll cooldown L8219-L8227 | `_stage_click_cooldown_until` is not reset at the `STAGE_SELECT` boundary; inspect whether stale cooldown can suppress first click after re-entry. This is a concrete regression candidate, not proof of a production incident. |
| `_stage_attempt_budget` | Stage-select → start transition | Created L7844-L7852; deliberately persists across stage-page fallback; cleared on MAIN_LINE entry L5969-L5972 | Intentional transition budget persistence; do not reset on every phase hop without preserving timeout semantics |
| `_room_start_deadline`, `_room_start_next_retry_at` | Room-start step | Cleared when leaving `ROOM_STARTING` L5888-L5890; initialized on accepted start | Correctly step-scoped |
| `_room_action_attempts` / `_room_action_deadline` | Room/create/start transition | Written at accepted actions L8138-L8141/L8340-L8341; callers intentionally preserve timeout retry budget | Business transition budget, not generic panel retry |
| `_selection_repeat_key`, `_selection_repeat_attempts` | Panel episode | Reset at MAIN_LINE L6001-L6003 and panel entry/exit L9035-L9038 | Existing fingerprint repeat guard is present |
| `_pending_action` and `_pending_action_unconfirmed_count` | Pending postcondition action | Created for inventory/hero actions L3735-L3772 and checked L9560-L9578 | **Leak risk:** no general phase-transition reset in `set_phase`; only main-line pending check clears/handles it. A pending inventory action surviving an abnormal phase transition is possible unless the caller clears it. |
| `_surface_conflict_since`, `_ambiguous_giveup_frames` | Current panel/scene episode | Conflict timestamp is handled in interaction arbitration L10006-L10034; fields are initialized in constructor | `_surface_conflict_since` is cleared on non-conflict, but neither field has a single round boundary reset. Their telemetry may span rounds. |
| `_equipment_fsm` | Equipment interaction/round | Constructed once at L812; `MAIN_LINE` reset block L6093-L6116 does not recreate/reset it | **Leak risk:** an equipment FSM lease/quarantine may survive a new round. `EquipmentFSM` only permits usable states `READY/CONFIRMED/EXPIRED`; `QUARANTINED` is not automatically usable. Need fixture evidence before resetting. |
| `_merchant_fsm` | Merchant panel episode | Constructed once; absent/panel observation creates fresh state behavior in merchant flow L4084-L4190 | No confirmed leak from current source; if a new round opens directly on a merchant panel, constructor-only state deserves a focused fixture. |
| `_runtime_watchdog_hud_confirmations`, `_runtime_watchdog_last_frame_id` | Consecutive HUD observation episode | Initialized/reset in runtime constructor and dependency prep L35-L51/L85-L90; `_runtime_watchdog_hud_confirmed` uses frame identity L268-L287 | **Leak risk:** no explicit `set_phase(MAIN_LINE)` reset. A prior two-frame latch can survive a phase return if frame identity is reused. |
| `_physical_panel_*` runtime guard | Physical panel episode | Reset on panel disappearance after 1s and at runtime reset paths L332-L341/L417-L430 | Mostly scoped; repeated same kind/HWND reappearance before the 1s absence threshold retains guard state by design. The key omits size/position/ui scale/generation. |
| `_old_world_switch_attempts` | Stage-select tab-switch attempt budget | Initialized/reset L564-L566/L5926-L5928 and incremented around L8219-L8227 | **Gap:** source comment says upper bound 2, but no direct comparison/Fail-Closed guard was found; actual protection comes only from surrounding generic budget. |
| `_boss_clicked`, `_f1_fallback_done` | Legacy/telemetry-looking flags | `_boss_clicked` is initialized L536 and has no later read/write; `_f1_fallback_done` is reset but no effective guard use was found | Dead/stale fields; they do not provide retry protection. Do not build reset semantics around them. |
| matcher `_TEMPLATE_CACHE`, `_SCALE_CACHE`, gray/hash caches | Process/session static resources | `clear_template_cache()` L95-L103 for tests/hot reload | Not transient scene state; no reset per round is expected |

### 2.2 Timer/budget conclusions

- Most explicit deadlines are fixed at action/round start and do not renew on periodic progress. Recovery has a fixed total deadline and per-step attempt cap (`mediator.py` L6143-L6452).
- `HitchSearchSM` has bounded join/search/refresh semantics, but direct `reset_lobby` does not reset every rotation-related field; the mediator normally replaces the state machine in `_hitch_after_exit`. Direct helper use therefore deserves a focused reset test.
- The strongest confirmed long-thread gaps are not “all timers leak”; they are the watchdog latch, pending action, dynamic hitch exit flags, and possibly equipment FSM/cooldown boundary listed above.

---

## 3. FrameEvidence freshness and authority

### 3.1 Existing implementation

`mediator.py:129-142` defines `FrameEvidence` with:

- strong `frame_ref`;
- monotonic `gen`;
- `ui_scale` and `hwnd` context;
- per-frame `cache` and cached `context`.

`_ensure_evidence` L1331-L1350 reuses evidence only when the same frame object and the same HWND/UI scale are present. `invalidate_evidence` L1352-L1362 increments `ev.gen`, clears cache/context, and retains the evidence object. `_memo` L1364-L1377 only memoizes when the supplied frame is the evidence frame.

Successful input is centralized through `_finish_input`/`act_click`/`act_key` around L1641-L1714. It increments input sequencing for successful input; LIVE successful input invalidates evidence. Dry-run intentionally does not perform the LIVE invalidation.

### 3.2 Facts and gaps

1. **Same-frame authority is mostly present.** A single `tick(frame)` passes the same frame into scene, panel, matcher, OCR and postcondition helpers. `FrameEvidence` prevents repeated recognition work on that frame.
2. **Post-input invalidation exists but does not itself create a fresh frame.** `_fill_room_dialog` and raw stage-scroll paths manually invalidate after direct executor operations (L7817-L7832 and L8255-L8266).
3. **A later tick can reuse a prior `Frame` object.** `see()` L1252-L1263 reuses the prior frame when captured pixels/position are unchanged. It preserves the old frame object/timestamp. The reuse comparison also omits HWND/window title/role, so identical pixels from another window can retain an old target identity. Therefore the aspirational invariant “postcondition frame timestamp must be greater than input time” is not implemented by `FrameEvidence` alone.
4. **`_ensure_evidence` does not compare every geometry field.** It checks frame identity, HWND and UI scale, but not width/height/left/top when the same object is reused or mutated.
5. **PendingAction does not enforce generation/timestamp.** `PendingAction.is_confirmed` simply calls its verifier, and mainline pending verification at L9560-L9578 supplies the current frame without a generation/issued-at assertion. Panel mutation confirmation similarly uses current ROI/baseline at L9098-L9110. `IncidentArchiver.attach_frame_after` also trusts the caller and does not prove that the after frame is newer.
6. **Failure preemption’s two-frame count is not generation-safe.** `mediator.py` L8770-L8795 counts consecutive failure observations but does not require distinct frame generations/objects. Since static-frame reuse is legal, identical evidence can satisfy the two-frame count.
7. **There is an input-gate interaction in `_fill_room_dialog`.** The loop calls `act_click` for each field; a successful first click advances `_input_seq`, so the second same-tick focus can be rejected by `_action_gate_ok` before the direct hotkey/paste path and manual invalidation. This is a concrete regression candidate and must be fixed only with a sibling test covering the complete dialog flow.
8. **No second FrameEvidence abstraction is justified.** Existing `FrameEvidence` can carry the required generation; the missing work is boundary enforcement and tests, not a parallel type.

**Risk conclusion:** stale postcondition evidence is a real code gap. It is distinct from the false claim that FrameEvidence is absent; FrameEvidence exists but callers do not uniformly enforce “after input = new evidence generation/new capture”.

---

## 4. Recovery / watchdog / ESC / back / close input map

### 4.1 Production paths

| Path | Visual authority | Fresh frame / postcondition | Budget and reset | UNKNOWN reachability | Finding |
|---|---|---|---|---|---|
| `RuntimeWatchdog-EscUnstuck` `runtime_mediator.py` L238-L320 | MAIN_LINE, two distinct frame IDs recognized as known in-game HUD; excludes post-game, pending action, non-closed panel, dry-run, and pre-wave protection | Input is guarded by `act_key`; next tick is expected to prove mutation/ownership through core FSM, but no dedicated PendingAction postcondition is attached | Fires after `_last_runtime_progress_at` stall (15s); **no attempt counter**; after successful ESC progress timestamp is refreshed; failed input leaves stall condition able to recur | UNKNOWN/non-HUD clears latch and grants no input | **High-risk gap:** repeated rejected/ineffective ESC can recur without a bounded count; no explicit postcondition is recorded. |
| `PanelFailForward-VerifiedClose` `runtime_mediator.py` L383-L400 | Known panel kind plus verified close anchor | WAIT_MUTATION with panel ROI baseline; panel disappearance/mutation is checked by core panel FSM | Physical panel deadline is bounded; recovery count has no global cap | Unknown panel has no close hit and cannot use close path | Existing safe close path; postcondition is panel mutation rather than click success |
| `PanelFailForward-Esc` L402-L414 | Same known physical panel watchdog context; ESC is fallback only after no trusted card/close result | WAIT_MUTATION and ROI baseline set after accepted input; generic ESC does not assert a dedicated business result | Immediate ERROR on input rejection; panel episode/deadline bounds exist, but repeated physical episodes have no global count | UNKNOWN itself does not call this method; runtime guard supplies known panel context | Safer than universal UNKNOWN→ESC, but still needs explicit action-attempt/incident metadata if converged |
| Failure/disconnect preemption `mediator.py` L8770-L8795 | `find_scene(disconnect/fail)` on consecutive observations, disconnect excludes fail | Recovery FSM uses known step anchors and postconditions; preemption frame count lacks distinct generation requirement | Recovery total deadline `min(setting,120s)`, per-step attempts `min(setting,3)`, interval setting | Unknown page does not enter recovery | Two-frame freshness gap; otherwise strongly bounded |
| Recovery FSM `mediator.py` L6143-L6452 | Per-step known fail/disconnect/close/retry anchors | Postconditions are explicit for most steps: dialog/mutation/disconnect absence or known next anchor | Fixed deadline, per-step attempt cap, interval; missing disconnect action button waits without consuming action attempt | No known anchor means zero input and bounded retry; UNKNOWN cannot grant arbitrary input | `FAIL_EXIT_CONFIRM` can finish after accepted click and defer room return verification to PREPARE; not all business mutation is proven before phase change |
| `HitchDismissPopup` L7315-L7342 | Known hitch popup or pending-join timeout; action routed via `act_key` | No explicit popup-disappeared postcondition after ESC; pending join is rejected in policy after accepted key | Pending join timeout exists, but generic popup branch has no explicit attempt cap | It is called from known hitch state branches, not generic UNKNOWN | Repeated popup ESC can recur while popup persists; needs a bounded mechanical retry contract |
| `HitchLeaveFloorOne` / `HitchConfirmLeave` L7260-L7310/L7360-L7384 | Blue exit/confirm visual controls and in-room context | Later lobby/in-room observation is the practical postcondition | No explicit attempt cap on exit/confirm | No universal UNKNOWN route | Exit action is visually constrained but lacks centralized same-target budget |
| `HitchLeaveRoom` L7399-L7403 | `GO_HOME` action hit from hitch action logic | `act_click` return is ignored; no explicit return-to-lobby postcondition here | No local time/attempt budget | Known hitch re-search branch only | **Concrete gap:** click result and postcondition are both weak; should not be part of a broad recovery rewrite |
| `HitchReady` L7321/L7387-L7394 | Known room controls and `_find_hitch_ready_button` | No frame-fresh postcondition/ready-state latch; only `_hitch_pending_row_y` is cleared | No explicit same-target retry budget | Known room branch, not generic UNKNOWN | A stale/delayed `room_ready` observation can cause repeated ready clicks. |
| `HitchSelectTab` L7416-L7425 | Room-list tab visual evidence | No postcondition that the list tab became active | No pending flag/cooldown; same anchor can be clicked every tick | Known hitch lobby branch | Repeated tab clicks are possible while the frame remains unchanged. |
| Hitch `GO_HOME` confirmation L7407-L7411 / `lobby_hitch.py:190-210` | `GO_HOME` target plus later lobby-visible boolean | Confirmation uses `now > clicked_at` and lobby-visible evidence; it does not require a new FrameEvidence generation/mutation | No same-target attempt cap on the action | Known hitch re-search branch | Stale static frame can satisfy return confirmation. |
| `HitchSearchBox` L7446-L7469 | Known search-box anchor | Accepted text input sets `_hitch_search_pending`; confirmation is expected through OCR, but after expiry/rejection the next input path does not consult `HitchSearchSM.next_allowed_at` | Search state has a 3s confirmation window, but the input branch can retype every tick while the anchor remains visible | Known hitch lobby branch | Concrete cooldown bypass; stale edit anchor can cause repeated typing. |
| `QuitGame-open-confirm` / `QuitGame-confirm` L10340-L10388 | Known game exit and confirm anchors | Phase NEXT/PREPARE plus later room-return verification; click success alone does not claim business completion | Three attempts plus transition timeout | No generic UNKNOWN path | Existing bounded path; verify sibling tests before changing |
| Panel close in core `_close_current_panel` L4226-L4280 | Anchor-derived close; runtime disables unsafe hide fallback | WAIT_MUTATION/panel state checks | Panel episode limits and cooldown | Unknown panel remains zero-input except known fail-forward | Existing `PendingAction`/panel FSM should be extended, not duplicated |
| Fixed-coordinate actions (e.g. artifact, pressure, pickup) | Caller-specific HUD/ROI checks; action goes through `act_key`/`act_click` gate | Several use progress timestamp or later state; not all have explicit business postcondition | Individual cooldowns; many reset at MAIN_LINE entry L6093-L6123 | Generic action gate blocks unknown context | Requires per-target audit, not blanket replacement |

### 4.2 Recovery conclusion

- The code does **not** implement a universal UNKNOWN→ESC path. That non-goal remains satisfied.
- Known-scene authority, fresh-frame gating, and bounded recovery are present for the primary failure FSM.
- The watchdog and hitch popup/leave paths are the highest-risk exceptions: repeated same-key/target behavior is not uniformly bounded and some paths lack a postcondition.
- Do not remove every ESC. Correct target is to bind only proven known-scene paths to bounded action/postcondition semantics, keeping business fallback in the caller.

---

## 5. Existing architecture reuse map

| Existing asset | Current implementation and actual capability | Status | Do not rebuild |
|---|---|---|---|
| `FrameEvidence` | `mediator.py:129-142`, lifecycle L1331-L1377; generation/cache/HWND/UI scale/same-frame memo | `ALREADY PRESENT` | Extend generation/issued-at enforcement at existing boundaries; no second frame type |
| `MatchResult` | `vision/matcher.py:15-27`: name, score, x/y/w/h, screen coordinates, center property | `ALREADY PRESENT` | Do not claim it already carries margin/ROI/gen/method/reason. Margin is separate `MatchMarginResult` around `matcher.py:516-520`; any enrichment needs compatibility evidence |
| `ActionLifecycle` | `interaction_surface.py:12-30`: OBSERVED, ACTION_AUTHORIZED, INPUT_SENT, VERIFYING, CONFIRMED, UNCONFIRMED, RECOVERING | `ALREADY PRESENT` | Do not introduce another action state machine |
| `PendingAction` | `interaction_surface.py:108-129`: kind, target_id, deadline, verifier, baseline fingerprint/count; `is_confirmed` and `is_expired` | `ALREADY PRESENT / LIMITED` | It is used for inventory/hero and tests, not a universal retry engine; evolve only if a specific repeated mechanical pattern proves it needs coverage |
| `IncidentArchiver` | `incidents.py:66-171`: before/now/after frames, metadata, ROI support, fingerprint dedup, bounded retention/bytes; `attach_frame_after` fills delayed after frame | `ALREADY PRESENT / ENRICHMENT POSSIBLE` | No second trace/incident service |
| matcher | `vision/matcher.py`: template load/scale/hash caches, `match_one`, `match_any`, margin search, `match_all`, ROI/multiscale, gray candidates, local color verification, HSV blue controls, geometry/contour helpers | `ALREADY PRESENT` | Count-color is not currently a general helper; add only for proven semantic color blind spots |
| OCR bootstrap | `runtime_mediator.prepare_live_dependencies` L95-L199 plus `ProductionShadowClient`; start/health/ping/warmup and LIVE fail-closed startup | `ALREADY PRESENT` | No second OCR service or runtime framework |

Important correction: `PendingAction` and `ActionLifecycle` are present but smaller than the external review assumed. They do not currently expose `action_id`, `postcondition`, `timeout_s`, or `retries_left` fields. `MatchResult` does not currently expose margin, ROI, frame generation, recognizer method, or reason.

---

## 6. External reference matrix: explicit Stage 0 classifications

Labels required by the addendum: `ALREADY PRESENT`, `MISSING`, `EXPERIMENT`, `REJECT`.
`EXPERIMENT` means a bounded comparison may be useful; it is not permission to implement it now.

| Reference point from addendum | Status | Current ShuaBao implementation / GT evidence | Decision |
|---|---|---|---|
| Airtest bounded `loop_find` timeout + interval | `EXPERIMENT` | `HitchSearchSM`, recovery deadlines, panel deadlines, and many cadence fields are bounded, but matcher APIs accept a supplied frame and do not provide one reusable bounded observe/retry primitive | Compare only if a concrete unbounded wait remains after focused audit; do not add Airtest dependency |
| Airtest color-correlation verification | `ALREADY PRESENT` | Local matcher has color/NCC-like verification and HSV/geometry helpers in `matcher.py`; no external Airtest source is bundled. Existing matcher tests/scene-template gate are the relevant GT | Reuse local matcher; no framework import |
| ok-script scene-local recognizer scheduling/rate limiting | `EXPERIMENT` | OCR call sites already have scene-specific timers (`_team_exit_ocr_next_at`, `_hitch_search_ocr_next_at`); no single scene scheduler controls all expensive recognizers | Audit/measure only at actual hot call sites |
| MAA RGB/HSV count evidence | `EXPERIMENT` | Current local color path is correlation/NCC and HSV/geometry; no reusable count/F1 helper is present. Existing rarity/bar/blue-control fixtures are potential GT | Pilot only on a proven enabled/disabled, selected, indicator, border, or progress semantic; hard AND gates for safety |
| MAA pure-color semantics | `EXPERIMENT` | Some local decisions already use HSV/coverage for rarity/blue controls, but there is no explicit pure-color profile contract | Do not generalize; require semantic-color GT and geometry/scene authority |
| MAA perception-only data configuration (ROI/template/threshold/color/regex) | `EXPERIMENT` | ROI and thresholds are mostly Python constants/settings; OCR `kind` and panel ROI already data-shape the recognizer, but workflow remains Python | Safe only for perception fields; reject `next`, fallback, arbitrary coordinates, or action sequences in data |
| OAS typed OCR (`digit`, `counter`, `lexicon_name`) | `MISSING` | OCR worker returns general candidates/raw text; callers locally parse discount/marker/prefix; no shared typed-read contract exists | Strong Stage 1 candidate; keep one small parameterized verifier, not subclasses |
| OAS per-target recognition intervals | `EXPERIMENT` | Two explicit OCR timers exist, but no generic per-target interval abstraction; panel OCR uses current panel fingerprint/cache | Add only when an expensive target is demonstrated to scan too frequently |
| Feature/SIFT matching | `MISSING` | No SIFT/feature matcher was found in current `src/shuabao`; fixed UI uses templates/geometry/color | `REJECT` for this phase: no proven target requiring it and YOLO/SIFT expansion is prohibited without GT |
| Incident evidence sufficient to turn a real failure into a regression fixture | `ALREADY PRESENT` | `IncidentArchiver` records before/now/after frames, caller-supplied metadata, ROI/caps/dedup. The generic archiver does not automatically know FrameEvidence generation, timestamp, action lifecycle, or PendingAction; `_incident_meta` currently supplies generation, phase/context, action/attempt/deadline and scenes. Convenient pending-action/release/runtime-health fields are missing | Enrich only with fields demonstrated missing in an actual diagnosis; real wrong-positive fixtures remain blocking |
| Same-target click/retry budget | `ALREADY PRESENT` | Panel fingerprint attempt counters, recovery per-step budgets, and transition-specific retry counters exist; `PendingAction` exists but is not generic. Hitch/watchdog paths expose missing bounds | Converge one proven mechanical pattern into existing lifecycle; no `VerifiedAction` duplicate |
| External Airtest/ok-script/MAA/OAS/Alas runtime/framework dependency | `REJECT` | No such runtime dependency is required by current architecture; local OpenCV/Paddle sidecar and FSM cover current fixed UI | Do not import framework or copy DSL/class hierarchy |

### Ground Truth caveat

The repository has offline tests, frozen replay, scene templates, and incident fixtures. It does not contain a verified 20-round real-machine capture baseline in this audit worktree, and the user prohibited real KK/SendInput. Synthetic replay is not real business PASS. Any Stage 1 proposal involving critical positive recall, real color blind spots, or recovery postconditions requires named existing GT fixtures or a later explicitly authorized real-machine run.

---

## 7. Stage 0 findings: facts versus hypotheses

### Confirmed code facts

1. Six direct production OCR prediction sites exist; none is unconstrained `VALUE_OPEN`.
2. The strongest typed/expected-value candidates are merchant `2折/5折` and hitch search-prefix confirmation.
3. `FrameEvidence` exists and is reused, but input invalidation does not force a new capture and `PendingAction` does not enforce generation/timestamp freshness.
4. Failure preemption can count reused static evidence as two observations.
5. Runtime watchdog ESC has known-HUD authority but no attempt cap or dedicated postcondition.
6. Hitch popup/leave input paths have incomplete same-target budgets/postconditions.
7. `_pending_action`, runtime watchdog latches, dynamic hitch exit flags, and possibly equipment FSM/cooldowns have boundary-reset risks; each needs focused regression evidence before code change.
8. Incident archiving already exists and contains substantial frame/action metadata; the archiver itself does not prove frame freshness, and the caller currently supplies generation where available. It is not a missing subsystem.

### Hypotheses requiring fixture measurement

1. Count-based RGB/HSV will improve any specific current NCC blind spot.
2. A typed verifier will improve recall without increasing UNKNOWN for discount/prefix fixtures.
3. Resetting equipment FSM or stage cooldown at a new boundary will improve long-thread behavior rather than hide a legitimate transition lease.
4. Genericizing `PendingAction` will reduce duplication without moving business fallback into a mechanical primitive.
5. A watchdog retry cap/postcondition choice will improve liveness without unacceptable completion loss.

---

## 8. Evidence-backed Stage 1 selection proposal (not yet implemented)

The following is the proposed 3-item workstream for approval. It is deliberately narrower than the candidate list; no Stage 1 production behavior was changed in this Stage 0 commit.

### A. Typed OCR / expected-glyph verifier

- Scope: prefix readback and merchant discount only, using one small parameterized helper or existing `lobby_hitch` utility; no OCR class hierarchy.
- Contract: bounded normalization, finite alphabet/format, parse/validation failure → UNKNOWN/false, preserve raw text/confidence in diagnostics.
- Required regression: wrong prefix blocks joining; valid `3`/`4` prefix and `2折`/`5折` fixtures retain acceptance; 8折/ordinary/garbled OCR remain rejected.
- Rollback: revert the single helper/call-site commit if critical-positive UNKNOWN or valid-label recall regresses against the current fixture baseline.

### B. Scoped transient reset at proven boundaries

- Scope: first tests for watchdog latch and dynamic hitch exit flags; then the smallest `set_phase`/episode reset that proves stale state survives. Do not mass-reset every field.
- Required regression: stale latch/flag from prior episode cannot authorize or suppress a new episode; legitimate in-progress transition budget remains intact.
- Rollback: revert only the reset commit if transition retry/soak fixture behavior changes outside the named stale-state case.

### C. One mechanical retry/postcondition convergence

- Scope: one watchdog or hitch same-target path, selected after focused tests. Extend existing `PendingAction`/`ActionLifecycle` only if its current fields can express the contract; otherwise keep the local smallest bounded guard rather than inventing `VerifiedAction`.
- Contract: known visual authority, fresh re-observation, one target, fixed attempt/time budget, typed failure, business fallback still in Policy/FSM.
- Required regression: rejected input or unchanged frame cannot loop indefinitely; click success cannot advance business state; UNKNOWN cannot authorize input.
- Rollback: revert only this workstream if the existing recovery/quit/postcondition regressions change.

**Not selected now:** count-based HSV/RGB, broad `MatchResult` enrichment, generic per-target scheduler, SIFT/YOLO, workflow DSL, FSM rewrite, universal recovery engine. Their Stage 0 evidence is insufficient or they violate the frozen architecture.

---

## 9. Stage 0 gate and next action

Stage 0 is complete when this document is committed separately and reviewed against the actual source. Before Stage 1 production edits, resolve the remote/base discrepancy and approve the 3-item proposal above. No real KK, `SendInput`, or physical machine action was run.

Recommended rollback point for this audit: commit `53e60ff` (Stage 0 audit commit) on top of the requested base `59833447b40706c533b4caecddcb94c3ee32e9f1`. The prior baseline behavior remains at `59833447b40706c533b4caecddcb94c3ee32e9f1`.
