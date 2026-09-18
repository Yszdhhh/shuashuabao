# ShuaBao Cloud Handoff — 2026-09-18

## Purpose

This is the current cloud-side handoff for the ShuaBao GT Test Candidate before Session A.

Read this file first in the next cloud conversation, then independently verify the live Git refs before trusting any local Agent report.

## Canonical refs at handoff time

Repository:

`Yszdhhh/shuashuabao`

Production branch:

`fix/solo-live-regression-20260915`

Production SHA:

`b52c69e2aa1f74b59506439cceba06535bc6234c`

GT Test branch:

`test/pirate-necromancy-gt-20260917`

GT Test SHA:

`47494cfcda9d758d1ae49151d2d98b769ee19d7a`

Important: this handoff is committed on a separate docs-only branch so the Test candidate SHA above remains unchanged while the local Claude audit is running.

## Cloud audit status

Cloud Git review is complete for the current candidate.

### CLOSED / PASS

- P0-1 round-boundary reset contract
- P0-2 ordinary devour fail-closed contract
- P0-2B obsolete test contract migration
- P0-3A production identity gate
- Win32 64-bit HWND FFI compatibility
- Production promotion to `b52c69e...`
- Production/Test SHA separation
- Exact TEST_ONLY_DELTA contract
- Production-critical equality checks
- src/config/tools clean gate for GT Test Candidate
- Test Dashboard second READY authority removed
- duplicate Test Dashboard Win32/OCR readiness logic removed
- native production MainWindow / operator APP_DATA entry removed from Test Dashboard
- canonical readiness -> PrepareOnly -> zero-input preflight chain wired into thin Test Dashboard
- canonical subprocess exit codes now authoritative and fail-closed

No currently known cloud-side P0 or P1 remains before local environment verification.

## Current Test Candidate identity semantics

The intended simultaneous state is:

- canonical Production Identity on the Test branch: `NOT_CLEAN`
- GT Test Candidate Identity: `READY`

This is expected because the Test branch intentionally carries declared Test-only source/config/tool deltas.

The Test candidate must fail closed if any of these become dirty or untracked:

- `src/`
- `config/`
- `tools/`

`captures/` and permitted evidence docs do not define the code-clean gate.

## Current thin Dashboard authority

`tools/test_dashboard.py` must not decide window/OCR/GT readiness itself.

The only valid chain is:

1. `live_scenario_capture.py readiness --quick --json`
2. `one_click_test.ps1 -PrepareOnly`
3. `live_scenario_capture.py preflight --json`

Each stage must satisfy both:

- subprocess exit code == 0
- its canonical semantic READY condition

Otherwise Dashboard remains BLOCKED and does not launch one-click.

## Local test anomaly still awaiting attribution

Before the final Dashboard exit-code micro-fix, one local run reported:

- `2404 passed`
- `18 skipped`
- `2 xfailed`
- `11 failed`

The previous Test HEAD had reported a full run with 0 failures.

The 11 failures were attributed locally to OCR/runtime paths, including a missing path under:

`C:\Users\10639\work\shuashuabao\.venv-ocr\Scripts\python.exe`

while the GT PrepareOnly evidence had resolved OCR under the G: workspace.

Cloud review did not find OCR production code, OCR fixtures, scene templates, frozen replay baselines, or release-gate logic changed by the Dashboard-thinning commits.

Therefore these failures are NOT accepted yet as either:

- confirmed new regression, or
- confirmed harmless historical debt.

They are pending local environment attribution by Claude.

## release_gate status

A local `python tools/release_gate.py` run was reported FAIL due to:

- pytest/OCR environment failures
- frozen replay deviations
- scene-template snapshot/statistic deviations

No baseline or fixture was updated.

Do not run `--update-baseline` merely to make the gate green.

The release gate is an offline release gate, not automatically identical to the Session A live-input gate, but unexplained new frozen replay or scene-template regressions must block Session A.

## Current local Claude task

Claude should audit the actual Windows machine, not redo the cloud Git architecture review.

Required local checks:

1. Verify local Test worktree branch/HEAD exactly matches:
   `47494cfcda9d758d1ae49151d2d98b769ee19d7a`
2. Verify Production SHA:
   `b52c69e2aa1f74b59506439cceba06535bc6234c`
   is an ancestor.
3. Verify `src/config/tools` are clean.
4. Record actual:
   - Python executable
   - imported `shuabao.__file__`
   - OCR Python
   - OCR model path/fingerprint
   - APP_DATA
   - operator settings path/hash
   - live lock
   - shortcut / launcher target if relevant
5. Explain why prior pytest resolved an OCR path under C: while GT evidence resolved the G: workspace.
6. Re-run the prior 11 failing tests in the corrected environment.
7. Then re-run full pytest.
8. Re-run `python tools/release_gate.py` without updating baseline.
9. Run `tools\one_click_test.ps1 -PrepareOnly`.
10. Run the canonical ZERO-INPUT preflight.
11. Do not start real live input.

Claude's final verdict must be exactly one of:

- `READY_FOR_SESSION_A`
- `BLOCKED`

## Rules when Claude reports back

In the next cloud conversation:

1. Read this handoff.
2. Independently verify remote refs first.
3. Do not trust the local report until Git identity is rechecked.
4. Separate local-only facts from Git-verifiable facts.
5. If Claude returns `READY_FOR_SESSION_A` with complete evidence:
   - stop further architecture/code churn
   - proceed to formal Session A live test planning/execution
6. If Claude returns `BLOCKED`:
   - classify the blocker first
   - do not automatically modify production code
   - local path/env/DB/shortcut issues stay local unless evidence proves a code defect

## Session A safety contract

No real input until formal zero-input preflight is READY.

For live execution:

- exact source identity required
- correct HWND required
- positive surface classification required
- OCR healthy where required
- single-instance lane required
- UNKNOWN/unclassified => ZERO INPUT
- click/input dispatch is not business PASS
- business postcondition required
- any unexplained real input => STOP + evidence
- first live FAIL/ERROR => STOP and seal evidence; no blind retry

## Git governance

At this handoff:

- no PR is required
- do not modify `main`
- do not modify Production unless a separately proven production defect is found
- do not force push
- do not rebase the active GT Test candidate while identity-sensitive local audit is running
- docs-only handoff branch may advance independently

## Next expected event

Wait for the local Claude audit report.

The next cloud conversation should continue from that report using this handoff as the cloud canonical context.
