# Architecture Convergence Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Reduce typed-OCR ambiguity, stale transient state, and unbounded same-target recovery retries without adding a parallel architecture or changing business fallback ownership.

**Architecture:** Keep the existing FSM and `FrameEvidence`/`PendingAction`/`ActionLifecycle` types. Add only a small typed OCR validation helper, explicit resets at proven episode boundaries, and one bounded mechanical guard on an existing hitch/watchdog path. Business decisions remain in `Mediator`/Policy; UNKNOWN remains zero-input.

**Tech Stack:** Python 3, stdlib `re`/`unicodedata`, existing OpenCV/Paddle sidecar, pytest, existing frozen replay and release gate.

**Spec:** `docs/ARCHITECTURE_CONVERGENCE_20260904.md`, `docs/LOCAL_AGENT_REFACTOR_HANDOFF_20260904.md`, `docs/ARCHITECTURE_STAGE0_AUDIT_20260904.md`

## Global Constraints

- Do not introduce Behavior Tree, statechart, workflow YAML/DSL, plugin architecture, microservices, YOLO-wide replacement, second FrameEvidence, second VerifiedAction, second OCR service, or second incident service.
- UNKNOWN, ambiguous, stale, or unclassified evidence grants zero input.
- Click/SendInput success is not business PASS; preserve explicit postconditions.
- Do not execute real KK, SendInput, or real-machine automation.
- Do not weaken fixtures, thresholds, baselines, or tests.
- Use test-first red/green cycles; each production behavior change must have a focused regression.
- Only stage named files; never use `git add .`, `git add -A`, `reset --hard`, or `git clean`.
- Canonical worktree: `G:/刷刷宝/Worktrees/architecture-convergence-20260904`.

---

### Task 1: Add typed expected-value OCR validation

**Files:**
- Create: `src/shuabao/vision/ocr_verifier.py`
- Modify: `src/shuabao/lobby_hitch.py` (expected-prefix helper)
- Modify: `src/shuabao/mediator.py` only if merchant call-site wiring is required
- Test: `tests/test_ocr_verifier.py`
- Test: the full existing sibling module covering lobby hitch and merchant OCR

**Interfaces:**
- Produces `verify_expected_text(text: str, expected: str, *, allowed_chars: str | None = None, max_length: int = 64) -> bool`.
- Produces `parse_counter(text: str, *, denominator: int | None = None) -> tuple[int, int] | None`.
- Normalizes only bounded text with Unicode NFKC, strips whitespace, rejects empty/overlong/disallowed text, and returns false/None on validation failure.
- `has_prefix_evidence` uses the helper with the configured numeric prefix and preserves the current fail-closed boolean contract.

- [ ] **Step 1: Write failing tests**

```python
def test_expected_text_rejects_disallowed_ocr_noise():
    assert verify_expected_text("3", "3", allowed_chars="0123456789")
    assert not verify_expected_text("3房间", "3", allowed_chars="0123456789")
    assert not verify_expected_text("", "3", allowed_chars="0123456789")


def test_counter_requires_valid_bounded_pair():
    assert parse_counter(" 3 / 4 ") == (3, 4)
    assert parse_counter("3/4", denominator=4) == (3, 4)
    assert parse_counter("3/5", denominator=4) is None
    assert parse_counter("3/", denominator=4) is None
```

- [ ] **Step 2: Run the new test and verify expected failure**

Run: `python -m pytest tests/test_ocr_verifier.py -q`  
Expected: collection/import failure because the helper does not exist yet.

- [ ] **Step 3: Implement the minimum stdlib helper**

Implement normalization, allowed-character membership, expected substring matching, and a strict `x/y` parser. Do not add classes, OCR worker changes, or a model-specific abstraction.

- [ ] **Step 4: Wire only the confirmed expected-value path**

Update `has_prefix_evidence` to call `verify_expected_text` with the normalized configured prefix and numeric alphabet. Keep the raw OCR response and existing callers unchanged. Do not modify panel category OCR or merchant normalization until the helper tests and existing merchant sibling tests establish a safe call-site contract.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_ocr_verifier.py tests/test_lobby_hitch_safety_regressions.py tests/test_l1_cycle_recheck_merchant.py -q --tb=short`  
Expected: all pass; existing wrong-positive discount tests remain blocking.

- [ ] **Step 6: Commit**

```bash
git add src/shuabao/vision/ocr_verifier.py src/shuabao/lobby_hitch.py tests/test_ocr_verifier.py
git commit -m "feat: validate expected OCR values before policy use"
```

---

### Task 2: Reset proven transient state at episode boundaries

**Files:**
- Modify: `src/shuabao/mediator.py` in `set_phase` and hitch episode reset helpers
- Modify: `src/shuabao/runtime_mediator.py` in MAIN_LINE/watchdog reset boundary
- Test: existing mediator/runtime/hitch test modules containing phase and recovery cases

**Interfaces:**
- No new public type or state container.
- Existing fields reset only where Stage 0 identifies a boundary leak: `_pending_action`, `_pending_action_unconfirmed_count`, runtime watchdog HUD latch, `_hitch_floor_exit_pending`, `_hitch_floor_exit_confirmed`.
- Preserve in-progress transition budgets such as `_stage_attempt_budget`, `_room_action_deadline`, and recovery step attempts.

- [ ] **Step 1: Write failing regression tests**

Add tests that construct the existing mediator/runtime objects, seed the stale field, invoke the actual phase/episode boundary, and assert the field is cleared while a legitimate transition budget remains unchanged. Do not use real input.

- [ ] **Step 2: Run the complete affected test files and verify red**

Run the full existing files containing these tests, not only the new test names. Expected: the stale latch/field assertions fail against current behavior.

- [ ] **Step 3: Implement the smallest boundary reset**

Add assignments at the existing `MAIN_LINE` and `_hitch_after_exit`/known episode boundary. Do not reset all timers or reconstruct `EquipmentFSM` without a failing fixture proving that behavior.

- [ ] **Step 4: Run complete affected test files**

Run the full mediator/runtime/hitch test files with `--tb=short`; expected all existing and new cases pass.

- [ ] **Step 5: Commit**

```bash
git add src/shuabao/mediator.py src/shuabao/runtime_mediator.py tests/test_n2_frame_evidence.py tests/test_lobby_hitch_safety_regressions.py tests/test_panel_liveness_harness.py
git commit -m "fix: reset transient recovery state at episode boundaries"
```

---

### Task 3: Bound one existing mechanical recovery path

**Files:**
- Modify: `src/shuabao/runtime_mediator.py` for `RuntimeWatchdog-EscUnstuck` or the specific hitch path selected by the failing regression
- Modify: `src/shuabao/mediator.py` only if the selected existing action lifecycle requires a caller-side postcondition field
- Test: full sibling test module covering runtime watchdog/recovery/hitch behavior

**Interfaces:**
- Reuse `act_key`/`act_click`, existing `FrameEvidence`, and existing postcondition/state checks.
- One mechanical target only; no business fallback or alternate target in the helper.
- A failed/unchanged postcondition consumes the bounded attempt budget and ends in the existing fail-closed result; it never converts UNKNOWN to input.

- [ ] **Step 1: Write a failing bounded-retry/postcondition regression**

Exercise the selected path with a known visual authority frame, an accepted or rejected action result, and unchanged postcondition evidence. Assert the number of inputs is bounded, the business phase does not advance on click success alone, and an UNKNOWN frame produces zero input.

- [ ] **Step 2: Run the full sibling recovery test module and verify red**

Run the entire module with `--tb=short`; expected the new boundedness assertion fails while baseline safety tests remain visible.

- [ ] **Step 3: Implement the smallest guard using existing lifecycle state**

Add only a fixed attempt/deadline field at the already existing episode boundary, reuse current `WAIT_MUTATION`/known-scene checks where available, and preserve Policy/FSM fallback ownership. Do not create `VerifiedAction`.

- [ ] **Step 4: Run the full sibling module**

Expected: all recovery, UNKNOWN-zero-input, click-vs-postcondition, and wrong-positive tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/shuabao/runtime_mediator.py src/shuabao/mediator.py tests/test_runtime_stability_hotfix_20260821.py tests/test_lobby_hitch_safety_regressions.py tests/test_panel_liveness_harness.py
git commit -m "fix: bound mechanical recovery retries"
```

---

### Task 4: Full verification and delivery

**Files:**
- No additional production files; update audit/implementation notes only if verification changes the stated facts.

- [ ] **Step 1: Run all focused test modules for Tasks 1–3**

Expected: PASS with no weakened fixture or threshold.

- [ ] **Step 2: Run the complete suite**

Run: `python -m pytest tests -q --tb=short`  
Expected: no regression against the Stage 0 baseline `1431 passed, 13 skipped, 2 xfailed`.

- [ ] **Step 3: Run release gate**

Run: `python tools/release_gate.py`  
Expected: all 4 stages PASS; retain and report any pre-existing `disconnect_modal_missing: BLOCKED` observation.

- [ ] **Step 4: Verify offline GT/replay and repository scope**

Inspect release-gate output, frozen replay results, changed-file list, and `git status --short`. Confirm no real KK/SendInput was run.

- [ ] **Step 5: Push only the named branch**

```bash
git push origin refactor/architecture-convergence-20260904
```

Do not merge or create a PR automatically. Report branch/base/head, commits, exact test/gate output, offline GT/replay status, real-machine status, blockers, rollback points, and merge recommendation.
