# Task 1 Report — typed expected-value OCR validation

Status: DONE (acceptance follow-up applied)
Commits: 01f297c, c943215, 55b58df, 42acb63, 67db284 (+ docs b23de45, f311a4a,
  43a7b40) on refactor/architecture-convergence-20260904
  on refactor/architecture-convergence-20260904

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
- `python -m pytest tests/test_ocr_verifier.py -q` → 13 passed (red first, then green).
- `python -m pytest tests/test_ocr_verifier.py tests/test_lobby_hitch_safety_regressions.py tests/test_l1_cycle_recheck_merchant.py -q --tb=short` → 58 passed.
- Extra sibling check (brief file list lacks test_lobby_hitch.py; only the safety-regressions sibling exists): `tests/test_live_scenario_capture.py -q` → 73 passed (covers `_hitch_search_text_override` + `has_prefix_evidence` path).

Formatters/linters/project-wide suites skipped per brief.

## Acceptance follow-up (01f297c)
Two findings, fixed in `has_prefix_evidence` (strict occupancy branch kept):
1. P1 wiring restored: the exact numeric-prefix branch again routes through
   `verify_expected_text(compact, want, allowed_chars=NUMERIC_ALPHABET,
   max_length=MAX_LENGTH)`, gated by `compact == want` so containment cannot
   widen the match. A spy test
   (`test_hitch_prefix_numeric_branch_uses_typed_helper`) asserts the branch
   calls the helper with the numeric alphabet.
2. Overlong expected rejected before truncation: the prefix is NFKC-bounded
   directly (`len > MAX_LENGTH` → False) instead of passing through
   `normalize_prefix`, whose 64-char truncation let `('3'*64, '3'*65)` match.
   Covered by `test_hitch_prefix_rejects_overlong_expected_before_truncation`.
Red confirmed on both before the fix. Focused suites green (ocr_verifier 13,
trio 58, live_scenario_capture 73); 26-case matrix smoke-checked OK including
`('3'*64,'3'*64)` pass and `('3'*64,'3'*65)`/`('3'*65,'3')` rejections.
## Final review compatibility fix (c943215)
Two findings, both fixed in `has_prefix_evidence` only (helper contract
unchanged, malformed/overlong still fail-closed):
1. Configured expected prefix was not normalized, so `('３','３')` failed.
   The expected word now also goes through NFKC + strip before comparison.
2. Legacy `_PREFIX_RE` accepted em dash `3—4`; NFKC does not map em dash to
   ASCII, so `_OCCUPANCY_RE` now includes `—` alongside `/` and `-`
   (`x/y`、`x-y`、`x—y`).
Direct regressions added: fullwidth prefix in both argument positions
(`('３','３')`, `('3','３')`, `('３','3')`), em dash occupancy `3—4`/`３—４`,
and new negatives `3—-4`, `3—`. Red confirmed on `('３','３')` before the fix.
Acceptance matrix smoke-checked: 23 cases (fullwidth prefix variants, em dash
forms, malformed shapes, trailing text, wrong prefix, empty, overlong 65 chars)
all behave as specified; focused suites green (ocr_verifier 11, trio 56,
live_scenario_capture 73).

## Re-review P2 fix (55b58df)
Finding: the 42acb63 alphabet widened `verify_expected_text` to digits+/-, so
malformed shapes passed: `3/`, `3//4`, `3/4/`, `3--4`, `3/-4`, `3/4 room`.
Fix (minimal, `lobby_hitch.py` only — helper contract unchanged):
- `has_prefix_evidence` no longer routes through `verify_expected_text`.
  It NFKC-normalizes, bounds to MAX_LENGTH, strips all whitespace, then either
  fullmatches the strict `_OCCUPANCY_RE` (`x/y` or `x-y`) requiring the leading
  x to equal the configured prefix, or accepts the whole compact string only
  when it equals the prefix over the numeric alphabet. Anything else fails
  closed. Fullwidth and whitespace variants (`３／４`, ` 3 / 4 `) normalize in.
Negative regressions added: `3/`, `3//4`, `3/4/`, `3--4`, `3/-4`, `3/4 room`,
`3房间`, `4/8`, empty; positives: `3`, `3/4`, ` 3 / 4 `, `3-4`, `3－4`, `３／４`.
Red confirmed on `3/` before the fix.
Acceptance matrix smoke-checked (15 positive/negative cases + classify_hitch_ocr
markers): OK.

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
