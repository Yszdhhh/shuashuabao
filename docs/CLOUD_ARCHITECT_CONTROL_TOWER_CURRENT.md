# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical handoff for the active ShuaBao control-tower state.
> Always read this file first from `handoff/latest`, then independently verify live Git refs before trusting any Agent report.
> This branch is documentation-only. Do not merge `handoff/latest` into production merely to carry status notes.

## 0. Executive state

Repository:

`https://github.com/Yszdhhh/shuashuabao`

Current production integration:

`trial-merge@d1fb4a51310f3f847ebeee110d51d8423050468b`

Parent production-code baseline:

`decb9b6eb3559e39ea51e26864eaada0d648855b`

`d1fb4a5` differs from `decb9b6` only by the two frozen Policy v0.1 documentation files.

Current status:

- `FINAL_FREEZE_HYGIENE = PASS`
- `CORRECTIVE_C_RELEASE_DEBT = CLOSED`
- `STANDARD_CI = PASS`
- `STANDARD_RELEASE_GATE = PASS`
- `STRICT_ZERO_DEFECT = NOT_RUN`
- `FROZEN_OCR_RELEASE_SMOKE = NOT_RUN`
- `LOCAL_WINDOWS_LAUNCHER_GT = SELF_REPORTED_PASS`
- `PRODUCT_GOLDEN_RUN = NOT_RUN`
- `PRODUCT_RELEASE_APPROVAL = NO`
- `COMPETITOR_A_C_CROSS_VALIDATION = COMPLETE`
- `STABILITY_SIMPLIFICATION_S0_CONTRACT = FROZEN_FOR_IMPLEMENTATION`
- `POLICY_V01_IMPLEMENTATION = HOLD_UNTIL_S0_VALIDATED`
- `MAIN_RECONCILIATION = HOLD`

Do not describe the current branch as full production-release PASS.

## 1. Frozen refs / Git topology

Keep immutable:

- `archive/final-green-trial-20260908` -> `decb9b6eb3559e39ea51e26864eaada0d648855b`
- `archive/final-policy-base-20260908` -> `d1fb4a51310f3f847ebeee110d51d8423050468b`
- `archive/old-main-20260908` -> `7edae9909ab1c757da27a45c4409f464aae66b04`

Old public `main` remains:

`7edae9909ab1c757da27a45c4409f464aae66b04`

Pre-stability ancestry-repair candidate:

`integration/reconcile-main-trial-20260908@1c8ef1ac53e2ee83dec73420f8ffef4aabb2b5a4`

It has old main + `d1fb4a5` as parents and a tree content-identical to `d1fb4a5`. Do not move `main` to it yet; S0 will create a newer final convergence target.

## 2. Final freeze closure

`decb9b6` closed the final two freeze-hygiene items:

1. physical Desktop shortcut capability failure now SKIPs only on GitHub Actions; ordinary local Windows fails instead of silently skipping;
2. stage-page ownership rejects explicit KK/platform frames before numbered-row authority, and lobby hitch requires verified game-client ownership before STAGE_SELECT progression.

Do not cherry-pick the old cloud-sync WIP; its useful stage ownership idea is already reimplemented and regression-tested in current production.

## 3. Policy v0.1

Frozen research baseline:

`a3bc4cdad0b11decaa578140e1a03c4b5380b8e7`

Frozen docs source:

`80e0bd89ee926bcf433f7492c9657f0b95f7c42b`

Canonical docs were migrated content-exactly to `d1fb4a5`:

- `docs/policy/POLICY_V01_IMPLEMENTATION_CONTRACT_20260908.md`
- `docs/policy/POLICY_V01_EVIDENCE_APPENDIX_20260908.md`

Policy production call paths were unchanged by the docs migration.

Policy implementation remains HOLD until S0 is implemented and validated.

## 4. Same-game competitor research — CLOSED FOR NOW

Canonical synthesis:

`docs/COMPETITOR_STABILITY_DECOMPOSITION_20260908.md`

Competitor C cross-validation:

`docs/COMPETITOR_C_CROSS_VALIDATION_20260908.md`

Research status:

- initial broad comparison: complete;
- Competitor A Checkpoint 1: PASS with precision corrections;
- Competitor A Checkpoint 2: PASS with precision corrections;
- Competitor C Checkpoint 3: PASS;
- Competitor B: HOLD / no further broad work;
- broad competitor research now STOPPED unless a specific later implementation question creates an evidence gap.

Cross-validated findings:

- `A_C_OWNER_LOCALITY = YES`;
- `A_C_PAGE_LOCAL_DETECTOR_AUTHORITY = YES`;
- `A_C_REDUCED_SHARED_TRANSIENT_STATE = PARTIAL`;
- `EVIDENCE_SUFFICIENT_TO_FREEZE_SHUABAO_S0 = YES`.

Important interpretation:

This does not prove either competitor is globally simpler or safer. It does show that two independent mature same-game implementations expose a narrower shared progression surface and constrain recognition/action authority more locally than ShuaBao's current explicit control graph.

Competitor C additionally provides readable evidence that hundreds of image assets can coexist with only a small page/job-specific active detector set, and that round-local retry/cooldown/window-monitor state can be explicitly reset at the next-round boundary.

Do not copy C's unsafe patterns: fixed-coordinate business actions, pure sleeps as confirmation, foreground-exclusive assumptions, weak disappearance-only completion, blind long waits, or any secrets/proprietary assets.

## 5. Stability Simplification S0 — FROZEN CONTRACT

Canonical implementation contract:

`docs/STABILITY_SIMPLIFICATION_S0_IMPLEMENTATION_CONTRACT_20260908.md`

S0 is now authorized for implementation on an isolated branch.

Frozen principles:

1. one clear business progression owner per active failure domain;
2. detector authority limited to verified current window/page/job;
3. mechanical helpers do not independently own business progression;
4. freshly re-observable scene facts should not become long-lived semantic latches;
5. keep only minimum asynchronous request/input/fresh-postcondition memory;
6. classify state lifetime and explicitly reset transient action/round state;
7. window ownership/activation gates recognition and input authority.

Mandatory current-SHA focus:

- audit and consolidate overlapping liveness/recovery ownership, especially Core-vs-Runtime mechanisms;
- unify `PLATFORM / GAME / UNKNOWN` authority without making `KK` alone a GAME grant;
- narrow detector/transition authority along the Golden Path;
- distinguish re-observable scene state from legitimate `PendingAction`/action-lifecycle memory;
- prove round reset boundaries for pending/retry/recovery state.

S0 is a simplification wave, not a feature rewrite. Do not start Policy v0.1, strategy scoring, OCR/CV framework replacement, UI redesign, auth work, or release/build work inside S0.

## 6. Non-negotiable safety invariants

- `UNKNOWN / ambiguous -> ZERO INPUT`.
- UNKNOWN may authorize bounded re-observation/reacquisition, never blind ESC/QUIT/HOME.
- Click/key/SendInput success is not business success.
- Frame mutation/bookmark/fingerprint change alone is not business completion.
- Business transition requires fresh, business-relevant evidence.
- Perception recovery, input retry and business fallback are distinct.
- Do not weaken tests, thresholds, fixtures or baselines merely to obtain PASS.

## 7. Parallel test / CI efficiency lane — AUTHORIZED

A separate branch may proceed in parallel:

`test/ci-speed-and-stability-harness-20260908`

This lane must remain non-overlapping with S0 production files.

Allowed:

- `.github/workflows/ci.yml`;
- test-only files under `tests/`;
- zero-input benchmark/audit tooling;
- test-harness documentation.

Forbidden in this lane:

- `src/shuabao/mediator.py`;
- `src/shuabao/runtime_mediator.py`;
- `src/shuabao/vision/capture.py`;
- `src/shuabao/interaction_surface.py`;
- Policy production/config;
- fixture/threshold/gate-baseline weakening;
- fixing discovered production defects directly — report them to the S0 owner.

### 7.1 Verified CI inefficiency

Current `.github/workflows/ci.yml` runs `python -m pytest tests -q --tb=short`, then calls `python tools/release_gate.py`.

`tools/release_gate.py::stage_pytest()` itself runs the complete `tests/` tree as the authoritative offline gate.

Therefore Standard CI currently executes the full Python test suite twice.

A CI-only branch should remove this duplicate execution while preserving the Standard Release Gate's complete pytest stage and failure semantics.

The same branch may evaluate splitting UI typecheck/unit/build from the Python Standard Release Gate into parallel jobs. `tools/release_gate.py` has no direct `ui-v2` dependency. Workflow success must still require both sides to pass.

Do not turn hosted-runner wall-clock performance timings into hard gates unless reproducibility is demonstrated. Prefer deterministic call-count/detector-surface contracts and keep hardware-sensitive timing as benchmark evidence.

### 7.2 Parallel test-harness work

Useful zero-input work that may proceed before S0 lands:

- characterize round/action/session state lifetimes and add tests for already-valid reset invariants;
- add a synthetic repeated-round harness that detects stale pending/recovery/cooldown state without sending real input;
- instrument detector/matcher call counts or active detector families on representative fixtures for before/after S0 comparison;
- preserve current business/safety semantics; if a characterization exposes an existing defect, report rather than changing production in this branch.

## 8. Release-gate distinction

Normal `trial-merge` push success remains only Standard CI / Standard Release Gate.

It does not substitute for:

- Strict Zero-Defect Release Gate;
- Frozen OCR Release Smoke;
- required local/real-machine GT;
- repeated post-S0 Golden Path validation.

Before release/main reconciliation, run the explicit release gates on the actual final candidate.

## 9. Git cleanup

Canonical cleanup manifest:

`docs/GIT_CLEANUP_MANIFEST_20260908.md`

Open PR count was cleaned to zero; stale superseded PRs were closed without merge.

Strong stale/superseded delete candidates are already recorded in the manifest. Diverged refs remain HOLD until semantic disposition. Do not merge old branches merely to preserve history.

The cloud connector does not currently provide remote branch-ref deletion; final `git push origin --delete ...` execution can be delegated locally once the manifest is complete.

## 10. Immediate sequencing / parallelization

Run three non-overlapping lanes:

### Lane A — S0 production implementation

Local main production Agent, fresh branch from exact `d1fb4a5`, following the frozen S0 contract. Require Failure Model + Contract Matrix before edits.

### Lane B — test/CI efficiency

Separate Agent/branch; workflow + test/harness only, no production S0 files. Primary quick win: eliminate duplicated full pytest and evaluate safe UI/Python job parallelism.

### Lane C — cloud control tower

Continue Git semantic cleanup, review both branches independently, and keep Policy/main reconciliation frozen.

After S0 and test/CI branches independently pass review, integrate in controlled order, run Standard CI, then fresh repeated real-machine Golden Path validation. Policy v0.1 resumes only after S0 validation.
