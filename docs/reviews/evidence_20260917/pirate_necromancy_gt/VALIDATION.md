# Validation — independent test branch only

## Observed checks

| Command / scenario | Actual result |
|---|---|
| `python tools/check_pirate_necromancy_profile.py` | Exit 0, offline_contract PASS; real profile validation/application, Settings roundtrip and policy assembly. Default ratio/time 0.8/480; profile 0.8/60; ordered existing Pirate/Necromancy groups; hard whitelist/min-confidence unchanged; starter must_take retained. |
| `python -m pytest tests/test_desktop_app.py -k pirate_necromancy -q -p no:faulthandler` | Exit 5, 103 deselected. Wrong selector; no tests executed. Not a PASS. |
| `python -m pytest tests/test_desktop_app.py -k test_profile_replaces_stale_shell_state -q -p no:faulthandler` first run | Exit 1, 1 failed: new test asserted Chinese 秘法师 against Settings.cards containing shortcode mfs. Test corrected to actual schema. |
| Same targeted command after correction | Exit 0; **1 passed, 102 deselected in 0.86s**. Includes stale selection removal, partial-profile preservation, group order, override and invalid-negative handling. |
| Actual PySide6 `MainWindow` with isolated temporary app_data, offscreen, apply real builtin profile, collect settings, grab image, close | Exit 0; advanced_packs=[haidao,wangling], unlock_s=60.0. No mocked window, no game input. |
| `python -c Settings._from_dict({'bond_advanced_unlock_s': True})` before fix | Returned `1.0` (bool swallowed by float()); proved a real defect. |
| Same probe after `settings.py` bool guard | Returns `None`; -1 → None; absent → None. Targeted test re-run: 1 passed. |

## Visual limitation

`preflight/dashboard_profile_offscreen.png` is a genuine widget capture, not synthetic UI. It shows the subscription/locked surface and missing-font square glyphs in this offscreen environment. Therefore it does **not** prove the visible profile selection UI or real desktop deployment works. The actual configuration callbacks and collection were exercised; visible Dashboard acceptance remains BLOCKED. No subscription/authentication gate was bypassed.

No desktop shortcut changed, no EXE rebuilt or deployed, and no game process started. The provided shortcut still launches the production source root, not this test branch. Deployment and real-machine GT remain BLOCKED.

## Full gate

No full gate verdict was obtained. Initial overlapping and later long runs were cancelled; a separate 90-second bounded release_gate attempt timed out at `[gate] pytest ...`. Subsequent full-suite attempts were also cancelled without a final result. No validation job is intentionally left running. No Harness baseline was updated. Commit/push is BLOCKED, not complete. Final profile has auto_secret_realm=true and its Settings/policy check passed after that change. Additional offline selections passed: secret_realm 12 tests; inventory-or-bag 116 tests. These do not replace the full gate.

## Model review

Read-only configuration review was cancelled without a final verdict. Code review is NOT_COMPLETED, not PASS; no model-identity claim is inferred from agent role names.
