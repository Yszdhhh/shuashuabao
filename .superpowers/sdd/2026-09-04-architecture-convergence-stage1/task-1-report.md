# Task 1 Report — typed expected-value OCR validation

Status: DONE

Commits: `01f297c`, `c943215`, `55b58df`, `42acb63`, `67db284` plus report
commits `b981a37`, `43a7b40`, `f311a4a`, `b23de45`; final coherent contract
fix is pending commit after this report update. Branch:
`refactor/architecture-convergence-20260904`.

## Final contract

- `src/shuabao/vision/ocr_verifier.py` remains stdlib-only (`re`,
  `unicodedata`) and exposes the required `verify_expected_text` and
  `parse_counter` APIs.
- `verify_expected_text` NFKC-normalizes and strips both input and expected,
  rejects empty/overlong values, validates both sides against `allowed_chars`
  when supplied, and requires exact normalized equality. Exactness prevents
  observed `444...` from authorizing expected `44`; invalid expected values
  (empty, whitespace, overlong, non-approved characters, malformed separators)
  fail closed.
- `parse_counter` accepts only bounded numeric `x/y`, `x-y`, or `x—y` text after
  NFKC/edge-strip normalization, with optional denominator equality; malformed,
  negative, incomplete, and overlong inputs return `None`.
- `lobby_hitch.has_prefix_evidence` is a thin compatibility facade: it cleans
  observed OCR only (NFKC, edge-strip, whitespace compaction), uses
  `parse_counter` to reduce a strict occupancy form to its numerator, then
  delegates expected-value authority to `verify_expected_text` with the numeric
  alphabet. It contains no independent expected normalization, comparison, or
  fuzzy acceptance grammar. Signature and fail-closed behavior are preserved;
  mediator callers are unchanged.
- Occupancy compatibility retained: `3/4`, `3-4`, `3—4`, fullwidth variants,
  and whitespace variants confirm prefix `3`; malformed/trailing/ambiguous
  forms (`3/`, `3//4`, `3/4/`, `3--4`, `3/-4`, `3/4 room`, `3房间`) do not.

## TDD and focused verification

- New tests were written before implementation; the initial run failed during
  collection with `ModuleNotFoundError: shuabao.vision.ocr_verifier`.
- Subsequent compatibility regressions were also red-first: occupancy `3/4`,
  malformed `3/`, fullwidth expected `３`, and helper wiring/overlong expected
  cases each failed before their corresponding fix.
- `python -m pytest tests/test_ocr_verifier.py -q` → **12 passed**.
- `python -m pytest tests/test_ocr_verifier.py tests/test_lobby_hitch_safety_regressions.py tests/test_l1_cycle_recheck_merchant.py -q --tb=short` → **57 passed**.
- `python -m pytest tests/test_live_scenario_capture.py -q` → **73 passed**.
- Direct 26-case acceptance matrix covered exact `3`/`44`, fullwidth prefixes,
  `/`/`-`/em-dash occupancy, malformed/trailing forms, invalid expected values,
  wrong prefix, empty, and overlong values; all behaved as specified.
- `git diff --check` passed before the final report-only changes.

The brief names `tests/test_lobby_hitch.py`, but that file is absent from this
worktree; the existing hitch safety, merchant, and live-scenario siblings were
run instead. No formatters, linters, project-wide suites, real input, or desktop
automation were run.
