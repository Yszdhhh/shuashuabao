# ShuaBao Stability Foundation V1 - Audit Report

## 1. Current verdict

- **Target Branch**: `stabilize/runtime-foundation-v1-20260819`
- **Baseline**: `abf3d35`
- **PR**: #13 (Draft)
- **Merge state**: NOT MERGED
- **Current release verdict**: **PENDING LOCAL RE-VALIDATION**

The earlier local run reported 1004 passed / frozen replay 7/7 / templates 132/132 / contract gate PASS. Those numbers predate the cloud-review hardening commits added after `c40bfa1`; they must not be reused as proof for the new HEAD. GitHub currently has no independent CI status attached to this private-branch workflow, so the current HEAD requires a fresh local gate and real-machine check before GO.

## 2. Cloud-review hardening added after the earlier GO claim

### A. Persistent physical-panel liveness

The core panel FSM already had a per-episode hard deadline. Cloud review found that a continuously visible modal could still cycle:

`episode timeout -> COOLDOWN -> CLOSED -> same physical modal -> new episode`.

Production `RuntimeMediator` now carries a cross-episode physical-panel watchdog. The watchdog survives core episode resets, requires sustained panel absence before clearing history, treats only post-condition confirmation as progress, and fails closed if the same physical modal remains stagnant beyond its macro deadline.

### B. One production Mediator

Desktop LIVE now imports only `shuabao.runtime_mediator.Mediator`. Runtime import failure refuses LIVE startup. There is no production fallback to the core Mediator.

### C. OCR True READY before business execution

Desktop LIVE now blocks the business loop until RuntimeMediator proves:

1. OCR worker start succeeds;
2. protocol ping succeeds;
3. real recognizer warmup succeeds;
4. health check reports process alive + ready + model validated + ping healthy.

Any failed stage closes the sidecar and refuses LIVE startup.

### D. ShuaBao-owned OCR production path

Production LIVE uses `ProductionShadowClient`, which intentionally does not use historical GameScript repository/env fallbacks. Development mode resolves a ShuaBao-owned `.venv-ocr` (or explicit `SHUABAO_OCR_PYTHON`). Frozen mode requires a standalone `ShuaBaoOCR.exe`; the main `ShuaBao.exe` is never accepted as a Python interpreter.

A reproducible `tools/bootstrap_shuabao_ocr.ps1` creates the current worktree's `.venv-ocr` from `requirements-ocr.lock` and validates Paddle imports/model presence.

### E. Packaged OCR sidecar

The release pipeline now contains a dedicated `ShuaBaoOCR.spec` + `ocr_worker_app.py`. `build_release.ps1` builds the OCR sidecar with the OCR environment, builds the main app separately, then assembles `vision/ShuaBaoOCR.exe` and `models/ocr` into the ShuaBao distribution.

**This packaging path is implemented but not yet independently validated on the local Windows machine after the cloud changes.** A successful PyInstaller build and cold-start run are required before release GO.

### F. Model identity telemetry

The worker still verifies each model file against the manifest size/SHA256. Its reported `model_hash` is now a deterministic fingerprint derived from those validated manifest file entries instead of reading a nonexistent `manifest_sha256` field.

## 3. Existing stability invariants retained

- Important card selections are staged on input and committed only after observed panel mutation/disappearance.
- CLOSING without a physical close anchor is bounded.
- Input evidence is invalidated on focus loss; focus reacquisition verifies the actual foreground HWND before business input continues.
- Failure/disconnect recovery is bounded and fail-closed.
- Windows OCR child creation uses `CREATE_NO_WINDOW` / hidden startup flags while keeping stdout/stderr piped for diagnostics.

## 4. Accuracy of implementation claims

- OCR restart behavior is **bounded retry + fixed cooldown**, not exponential backoff.
- `ActionLifecycle` enum documents desired lifecycle vocabulary; the production correctness mechanism remains the concrete pending-action / WAIT_MUTATION / post-condition code. Do not claim enum declaration alone is a separate fully-wired runtime FSM.
- `%APPDATA%\GameScript\Settings\Settings.json` remains only as an explicit legacy-upstream compatibility source. It is not a ShuaBao primary runtime path.

## 5. Required local re-validation before GO

1. Pull the latest PR #13 HEAD.
2. Run `tools/bootstrap_shuabao_ocr.ps1` so this worktree has its own ShuaBao OCR environment.
3. Run the full release gate and the new `tests/unit/test_runtime_foundation_hardening.py` suite.
4. Run `build_release.ps1 -NoDeploy` and prove the assembled distribution contains `ShuaBao.exe`, `vision/ShuaBaoOCR.exe`, and `models/ocr/PP-OCRv5_mobile_rec_infer`.
5. Cold-start the desktop app multiple times and confirm zero OCR console windows.
6. Kill the OCR worker during a controlled run; verify bounded recovery/fail-closed behavior.
7. Hold one central choice panel visibly stagnant and confirm it cannot evade the watchdog by cycling episode IDs.
8. Switch focus away from the game and back; verify stale evidence is discarded before new input.

Only after those checks produce fresh evidence for the current HEAD may this report be changed from **PENDING LOCAL RE-VALIDATION** to **GO**.
