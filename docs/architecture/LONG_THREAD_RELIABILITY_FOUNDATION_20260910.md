# Long-Thread Reliability Foundation (2026-09-10)

## 1. Executive Summary

Long-running unattended execution (12–48 hours) is the primary operational requirement for ShuaBao.
This document details the architectural failure modes identified during audits of ShuaBao and competitor scripts, and introduces the newly implemented **Six Reliability Foundations** in `src/shuabao/reliability_foundation.py`.

---

## 2. Long-Thread Failure Mode Taxonomy (The Failure Map)

Our investigation identified nine distinct failure modes that cause scripts to stall or corrupt state:

| Failure Mode | Mechanism | Observed Symptoms | ShuaBao Countermeasure |
| :--- | :--- | :--- | :--- |
| **P0-A: Process Alive but Business Dead** | Ticking loop continues running, but game is stuck on an unrecognized modal or black screen. | Loop timer resets; CPU usage normal; no game rounds advance. | **BusinessProgressToken + ProgressTracker**: Detects business stagnation independently of tick heartbeat. |
| **P0-B: Stale Window Binding** | Game window closes or crashes and relaunches with a new HWND/PID; script sends inputs to dead/background HWND. | `SendInput` returns 0; clicks land on desktop or other apps. | **BindingGeneration**: Invalidates all pending actions and perception caches when HWND changes. |
| **P0-C: Old Round Latch Leakage** | A latch set during round $N$ (e.g. "Merchant visited") persists into round $N+1$, causing round $N+1$ actions to be skipped. | Merchant or Treasure skipped on subsequent rounds; erratic phase jumps. | **RoundGeneration**: Bumps on genuine round transition, instantly clearing all round-scoped temporary latches. |
| **P0-D: Ambiguous Action Lockout** | Network lag causes a purchase or refresh click to delay visual feedback; script retries and double-spends currency. | Gold exhausted; duplicate cards bought; unintended card rerolls. | **TransactionGeneration + BusinessOutcome**: Blocks irreversible retries if prior state is `AMBIGUOUS`. |
| **P0-E: Observation Provenance Mismatch** | Template hit or OCR text from a prior frame is fed into an action generator after the window has resized or moved. | Clicks miss buttons by offset equal to window displacement. | **ObservationProvenance**: Pairs each observation with frame ID, HWND, and geometry signature. |
| **P0-F: Accidental Personal Item Destruction** | While attempting to deposit into Public Bag, script issues a left-click on a protected personal gear slot. | Personal equipment dropped, replaced, or sold. | **ActionSafetyPolicy Hard Deny**: Rejects `is_personal_resource_left_click` at the kernel level. |
| **P0-G: Modal Recovery Endlessly Repeats** | Script clicks "Confirm" on a dialog that requires player level or currency, which immediately re-opens. | Infinite click loop; 100% CPU in recovery loop. | **Bounded Recovery Episodes**: Cap consecutive recovery attempts per modal fingerprint to 3. |
| **P0-H: Native Resource Leaks (GDI / Handles)**| Creating GDI Device Contexts (`CreateCompatibleDC`, `GetDC`) without explicit `ReleaseDC` / `DeleteDC`. | Process crashes after 4–8 hours with Win32 Error 8 (Not enough memory). | Explicit `finally` release blocks; monitor process GDI handle count. |
| **P0-I: OCR Worker Queue Backlog** | OCR inference runs slower than frame grab rate; worker queue accumulates hundreds of stale frames. | High RAM consumption (several GBs); actions executed 10 seconds late. | Queue depth limit = 1 with drop-oldest policy for real-time perception. |

---

## 3. The Six Reliability Foundations (Implemented in `src/shuabao/reliability_foundation.py`)

All six primitives have been implemented as zero-dependency, additive, pure-Python modules covered by 17 unit tests in `tests/test_reliability_foundation.py`:

```
src/shuabao/reliability_foundation.py
├── 1. BusinessProgressToken & ProgressTracker
│   ├── Token enum: BOOT_CONFIRMED, LOBBY_CONFIRMED, ROUND_STARTED, etc.
│   └── ProgressTracker: Tracks progress milestones, age, and stagnation timeout
├── 2. Generation Invalidation Primitives
│   ├── BindingGeneration: HWND/PID/Geometry invalidation
│   ├── RoundGeneration: Inter-round latch cleanup
│   └── TransactionGeneration: Unique action transaction lifecycle
├── 3. ObservationProvenance
│   └── Metadata: frame_id, timestamp, backend, hwnd, pid, rect, dpi, binding_gen
├── 4. BusinessOutcome & ExecutionAssessment
│   └── Outcomes: CONFIRMED_SUCCESS, CONFIRMED_NO_EFFECT, REJECTED, AMBIGUOUS, OBSERVATION_FAILED
├── 5. ActionSafetyPolicy (Shadow Authorization Kernel)
│   ├── Verdicts: ALLOW, DENY_WRONG_HWND, DENY_STALE_BINDING, DENY_UNKNOWN_CONTEXT,
│   │            DENY_PROTECTED_PERSONAL_RESOURCE, DENY_AMBIGUOUS_TRANSACTION
│   └── Shadow authorization hook for ActionIntent
└── 6. RuntimeIdentityManifest
    └── Self-reporting manifest: source_sha, build_id, model_id, asset_id, etc.
```

### 3.1 Verification & Test Coverage
- Total Tests: 17
- Pass Rate: 100%
- Runtime: 0.06s
- Zero existing files modified; zero risk of conflict with ongoing live test branches.
