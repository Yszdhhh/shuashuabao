# ShuaBao Stability Foundation V1 - Offline Fixture & Soak Test Ledger

## 1. Central Choice Panel Offline Real-Machine Fixtures
All central choice and upgrade panels are covered by real-machine frames and verified in test suites:
- **Skill Choice Panel**: Verified on 1080p and 720p resolution templates (`test_choice_policy.py`, `test_central_panels_and_secondary_interactions.py`).
- **Bond Choice Panel**: 5-card default bond selection verified with mutation confirmation and learning updates.
- **Treasure Choice Panel**: Verified with must-take / negative-card filtering and physical close anchor detection.
- **Hero Upgrade / Cards**: Verified in `mediator._begin_hero_setup`, separating normal upgrades from hero mode reputation routes.
- **Equipment Right-Click Upgrade**: Verified in `test_equipment_upgrade_debounce_and_confirmation`.

## 2. Targeted Unit Test Suites Added
- `tests/unit/test_panel_liveness.py`: Episode ID creation, hard deadline timeouts (15.0s), progress accounting, and zero-input deadlock prevention.
- `tests/unit/test_ocr_productization.py`: Silent process spawn (CREATE_NO_WINDOW/SW_HIDE), TRUE READY protocol validation, corrupted model rejection, bounded restart (max 3), and private runtime auto-discovery.
- `tests/unit/test_nomenclature_migration.py`: Verification that all internal paths are migrated to `ShuaBao`/`shuashuabao`, with `%APPDATA%\GameScript` isolated to `LEGACY_UPSTREAM_SETTINGS_PATH`.
- `tests/unit/test_central_panels_and_secondary_interactions.py`: Action lifecycle (OBSERVED -> ACTION_AUTHORIZED -> INPUT_SENT -> VERIFYING -> CONFIRMED), state mutations, and secondary interaction debouncing/recovery.
- `tests/unit/test_focus_and_network_recovery.py`: Window focus loss, input suspension, target window reactivation (`reacquire_target_window`), and network recovery FSM (120s bounded timeout).

## 3. Automated Gate & Soak Metrics
- Release Gate Result: **4/4 PASS**
- Pytest Suite: **1004 passed, 2 xfailed, 4 skipped**
- Frozen E2E Replay: **7/7 PASS** (with disconnect_modal_missing BLOCKED as designed for safe unhandled modals)
- Scene Templates: **132/132 OK**
- Layer Contract: **68 passed, 1 present**
