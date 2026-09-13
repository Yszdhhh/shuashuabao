# External Review Notes — Fable 5.1 (2026-09-04)

This note records only the external-review conclusions that are useful to later code work. It is not a source of truth for current ShuaBao implementation; the Git tree and real-machine evidence remain authoritative.

## Adopted hypotheses

- Preserve the current FSM; converge boundaries instead of replacing the paradigm.
- Prefer typed OCR reads for Policy paths and finite visual verifiers where the business only needs an expected/category result.
- Treat count-based RGB/HSV evidence as distinct from NCC/correlation evidence; test it only on color-semantic targets.
- Keep mechanical retry/cooldown/timeout close to the action lifecycle, while business fallback stays in Policy.
- Centralize recovery governance, not universal recovery actions; UNKNOWN itself never grants input authority.
- Treat frame freshness, transient-state scope/reset, bounded waits and incident capture as long-thread invariants.
- Reuse real incident fixtures as safety regressions and separately track availability/recall so the system cannot become safely unusable.

## Explicit corrections / non-adopted external claims

- Do not assume current MAA uses geometric-mean fusion from a changelog. Current `dev-v2` source observed during review computes color F1 and multiplies it with the template result.
- Do not implement a blanket 24–72 hour offline lease before Beta evidence proves permit refresh is a real availability problem.
- Do not interpret replay as uniformly non-blocking; historical real incident regressions can and should block wrong-positive regressions.
- Do not infer test-health from test count alone.
- Do not implement generic `UNKNOWN -> ESC/back/home` recovery.
- Do not move workflow/action policy into hot-updatable perception data.

## Current Git facts that already falsify some external assumptions

Direct inspection of `trial-merge` shows existing building blocks:

- `Mediator.FrameEvidence` already provides generation-scoped frame evidence/cache semantics.
- `interaction_surface.ActionLifecycle` and `PendingAction` already represent action/postcondition lifecycle pieces.
- `IncidentArchiver` already records abnormal/unknown evidence and ROI crops.
- `vision.matcher` already implements gray candidate matching, local color NCC verification, ROI/multiscale/margin logic and HSV/geometry helpers.
- `runtime_mediator` already performs bounded OCR bootstrap/warmup and contains liveness guards with multi-frame HUD evidence.

Therefore implementation must extend/consolidate these structures rather than create parallel replacements.

## Code-agent verification priorities

1. Audit production OCR call sites and identify actual open-value vs expected-value/category use.
2. Audit NCC color verification versus count-based color needs on real fixtures.
3. Audit retry/cooldown/cache scope and reset boundaries across scene/round/session.
4. Audit frame freshness/invalidation across SendInput and postcondition paths.
5. Audit all recovery/liveness input authority, especially ESC/back/watchdog paths, for fresh known-scene authority, bounded attempts and postconditions.
