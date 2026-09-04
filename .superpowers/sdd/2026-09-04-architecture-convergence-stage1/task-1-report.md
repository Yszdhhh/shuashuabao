# Task 1 Report — typed expected-value OCR validation

Status: DONE (reviewer follow-up applied)
Commits: 42acb63, 67db284 (refactor/architecture-convergence-20260904)

## Scope
- New `src/shuabao/vision/ocr_verifier.py`: stdlib-only (`re`, `unicodedata`) helpers
  `verify_expected_text(text, expected, *, allowed_chars=None, max_length=64) -> bool`
  and `parse_counter(text, *, denominator=None) -> tuple[int, int] | None`.
- NFKC normalization, whitespace strip, empty/overlong (>64) rejection, optional
  per-character alphabet check, substring containment for expected text; counter
  uses fullmatch `x/y` with optional denominator equality. All failure paths
  return False/None (fail-closed).
- `lobby_hitch.has_prefix_evidence` now delegates to `verify_expected_text` with
  `normalize_prefix(prefix)` and `NUMERIC_ALPHABET`; bool signature unchanged,
  callers in `mediator.py` untouched.
- New `tests/test_ocr_verifier.py` written first; red run confirmed
  (`ModuleNotFoundError: shuabao.vision.ocr_verifier`) before implementation.
  Now 12 cases (helper + reviewer regressions).

## Focused tests
- `python -m pytest tests/test_ocr_verifier.py -q` → 12 passed (red first, then green).
- `python -m pytest tests/test_ocr_verifier.py tests/test_lobby_hitch_safety_regressions.py tests/test_l1_cycle_recheck_merchant.py -q --tb=short` → 57 passed.
- Extra sibling check (brief file list lacks test_lobby_hitch.py; only the safety-regressions sibling exists): `tests/test_live_scenario_capture.py -q` → 73 passed (covers `_hitch_search_text_override` + `has_prefix_evidence` path).

Formatters/linters/project-wide suites skipped per brief.

## Reviewer follow-up (42acb63)
Finding: `has_prefix_evidence("3/4", "3")` returned False because the numeric
alphabet rejected the `/` separator, breaking legacy occupancy forms.
Fix (minimal, in `lobby_hitch.py` only — helper contract unchanged):
- Alphabet widened at the call site to digits + `/-` separators, and an anchored
  `_OCCUPANCY_RE` path (`_occupancy_forms`) accepts `x/y`, `x-y` (ASCII and
  fullwidth via NFKC) when the leading x equals the configured prefix.
- Still rejects non-numeric noise: `3房间` → False, `4/8` with prefix `3` → False.
- Red-first regressions added (`test_hitch_prefix_accepts_occupancy_form`,
  `test_hitch_prefix_rejects_non_numeric_noise`), plus helper-level
  negative/overlong/separator cases; red confirmed on `3/4` before the fix.
Acceptance matrix smoke-checked: `3/4`/`3-4`/`3－4`/` 3 / 4 ` → True,
`3房间`/`4/8`→False/`""`→False, plain `3` → True.

## Notes / concerns
- NFKC maps fullwidth digits to ASCII digits, so the numeric alphabet check runs
  post-normalization; a fullwidth `３` OCR result still passes as `3`. If
  fullwidth glyphs must be rejected pre-normalization, that is a behavior change
  beyond this brief.
- `verify_expected_text` alphabet check applies to the input text only; expected
  text is bounded and non-empty but not alphabet-checked (matches brief wording).
- The brief's test list includes `tests/test_lobby_hitch.py`, which does not
  exist in this worktree; nearest siblings (safety regressions, L1 merchant,
  live scenario capture) all pass.
