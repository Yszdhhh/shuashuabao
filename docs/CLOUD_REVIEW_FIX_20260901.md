# Cloud Review Safety Fix — 2026-09-01

Scope: code/offline remediation only. This record does **not** upgrade any missing real-machine evidence to PASS.

Baseline reviewed: `fd0bcbb3ff2fc7657845ab208915c806844e3f50`.

Applied safety corrections:

- Hero-focus F1 recovery now requires a positively recognized in-game HUD and two distinct captures with the hero panel missing. UNKNOWN/transition/frozen captures grant zero input authority.
- Unknown choice-panel handling keeps the existing shadow evidence but no longer emits physical F1 input.
- Archive pending-only and archive/heirloom destination HUD confirmation no longer count an unchanged/reused capture as a second frame.
- Desktop preflight can start legitimately from the KK L0 lobby without incorrectly reusing the configured L1 game-title filter.
- `main.py run` no longer provides a second real-input path that bypasses DashboardFacade/RunnerService entitlement, readiness and build-identity gates.
- Console logging tolerates Windows consoles whose active encoding cannot represent Unicode log glyphs.
- Two CI tests were isolated from unrelated host assumptions: incident archiving explicitly disables OCR for that test, and the AppData assertion normalizes Windows path aliases.

Evidence boundary retained:

- `disconnect_modal_missing` remains BLOCKED until a real sample exists.
- Current-SHA archive/heirloom post-click timing still requires real-machine confirmation.
- Full Time Cave NPC entry and Great Rift real activation still require real-machine confirmation.
- No baseline, fixture, template or frozen-replay status was changed to make a gate green.
