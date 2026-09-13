# SOURCE OF TRUTH MANIFEST (2026-09-09)

## 1. Cloud Refs & Commit Identifiers

| Identifier | Branch / Ref | Commit SHA | Role / Identity | Status / Notes |
|---|---|---|---|---|
| **FORMAL_G0_SHA** | `origin/refactor/stability-s0-20260908` | `d9148c893f160a6486aeedc8f106fa764be7d931` | **FORMAL_PRODUCTION** | Latest formal G0 tip (2026-09-09 20:53:42). Reconciled pressure 40-tick budget, archaeology zero-input fail-closed, and ported verified 53afb437 lobby contracts. |
| **LOBBY_CANDIDATE_SHA** | `origin/test/lobby-hitch-surface-correction-20260909` | `53afb4376bd371c3e7bdffd7fff1f13eb6cfd1a5` | **LOBBY_TEST_CANDIDATE** | Lobby hitch test candidate. Core surface changes ported to formal G0 at `d9148c8`. |
| **HARNESS_SHA** | `origin/test/live-harness-current-20260908` | `ff54891d1cf3087471ab1ec1a7b66e7fc27bd8da` | **LIVE_HARNESS** | Live harness benchmark tracking ref. |
| **MERGE_BASE** | `merge-base(FORMAL_G0_SHA, LOBBY_CANDIDATE_SHA)` | `1c45d8e07f1509b56b6a614805752000749c2261` | Common Ancestor | Divergence point: `1c45d8e fix(lobby): unify hitch platform modal ownership`. |

## 2. Identity Disambiguation & Line Separation Contract

1. **FORMAL_PRODUCTION (`d9148c8`)**:
   - Sole authority for production bug fixes, release gates, and production runtime lines.
   - Contains reconciled pressure and archaeology logic, and ported 53afb437 lobby surface logic.
   - Any gap verification in this audit MUST target `d9148c8` verbatim.

2. **LOBBY_TEST_CANDIDATE (`53afb43`)**:
   - Historic/parallel verification worktree for lobby hitch platform modal and seat resolution.
   - Retained as audit reference to separate test-only hunks from production lines.

3. **LIVE_HARNESS (`ff54891`)**:
   - Dedicated testing and benchmark harness runner.
   - Not a production runtime target.
