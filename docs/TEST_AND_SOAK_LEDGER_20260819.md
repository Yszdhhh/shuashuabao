# ShuaBao Stability Foundation V1 - Test & Soak Ledger

## Status

This ledger separates **historical local results** from evidence that must be rerun for the current PR #13 HEAD.

The previously reported values below were produced before the cloud-review hardening commits that changed RuntimeMediator, desktop LIVE startup, OCR bootstrap, production OCR runtime resolution, and the release packaging pipeline. They remain useful regression baselines, but they are **not current-head release evidence**.

## 1. Historical local baseline (pre cloud-hardening)

- Pytest: `1004 passed, 2 xfailed, 4 skipped`
- Frozen replay: `7/7 PASS`
- Scene templates: `132/132 OK`
- Layer contract: reported PASS
- Release gate: reported `4/4 PASS`

GitHub has no independent CI status for that run.

## 2. Existing fixture/test coverage

Existing test suites cover important pieces including:

- skill/bond/treasure selection policy and post-click mutation confirmation;
- hero setup / hero-card related routes;
- equipment right-click upgrade debounce;
- per-episode panel hard deadlines and missing-close handling;
- Windows hidden OCR child-process flags;
- model missing/corrupt rejection;
- OCR protocol timeout/restart behavior;
- focus loss and bounded disconnect recovery.

These tests should all remain green after syncing the current HEAD.

## 3. New cloud-hardening targeted suite

`tests/unit/test_runtime_foundation_hardening.py` was added specifically for the review blockers and must be run locally. It verifies:

1. LIVE OCR bootstrap order is `start -> ping -> warmup -> health`.
2. warmup failure is fail-closed and closes the sidecar.
3. a persistent physical choice panel cannot evade the watchdog by resetting a core panel episode.
4. physical-panel history is cleared only after sustained absence, not a one-frame miss.
5. frozen runtime never accepts `ShuaBao.exe` as the OCR interpreter.
6. packaged runtime requires/resolves `ShuaBaoOCR.exe` as an explicit standalone worker command.

## 4. Required current-head automated validation

Run from the synced branch:

```powershell
powershell -ExecutionPolicy Bypass -File tools\bootstrap_shuabao_ocr.ps1
python -m pytest tests\unit\test_runtime_foundation_hardening.py -q
python tools\release_gate.py
```

Also rerun the project's existing frozen replay / template / contract commands used by the prior gate and record their exact outputs against the new HEAD SHA.

## 5. Required packaging validation

Run:

```powershell
powershell -ExecutionPolicy Bypass -File build_release.ps1 -NoDeploy
```

Record evidence that the assembled distribution contains at minimum:

- `dist\ShuaBao\ShuaBao.exe`
- `dist\ShuaBao\vision\ShuaBaoOCR.exe`
- the OCR sidecar onedir support payload adjacent under `vision\`
- `dist\ShuaBao\models\ocr\PP-OCRv5_mobile_rec_infer\...`

Then launch the built main executable and prove the packaged sidecar reaches `LIVE READY` without a visible console.

## 6. Required real-machine soak ledger

A real soak entry must contain actual session facts, not only the word PASS. For every validation session record:

- branch + HEAD SHA;
- start/end timestamps;
- number of completed rounds;
- choice panel episode count by kind;
- confirmed/unconfirmed action counts;
- persistent-panel watchdog trips;
- OCR starts/restarts/unavailable events;
- window-focus recovery events;
- disconnect/network recovery events;
- incidents written;
- final process/round outcome.

Minimum controlled scenarios for this hardening wave:

1. **Cold startup**: repeat startup several times; zero OCR console/black-window flashes.
2. **OCR fault**: kill OCR sidecar during a controlled run and record bounded recovery/fail-closed result.
3. **Persistent panel**: intentionally hold a central selection panel with no executable progress; prove it cannot loop through fresh episode IDs indefinitely.
4. **Focus loss**: switch to another application and back; prove no stale pre-focus-loss coordinate authorizes input.

## 7. Release decision rule

Until the current HEAD has fresh automated + packaging + real-machine evidence recorded above, the branch status is:

**PENDING LOCAL RE-VALIDATION — DO NOT MERGE**.
