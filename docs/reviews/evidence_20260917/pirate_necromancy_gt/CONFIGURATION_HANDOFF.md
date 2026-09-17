# Configuration handoff — TEST_ONLY / PROPOSED_PRODUCTION_CHANGE

Starting SHA: `5b0f2436c5fe8ec2057f4266f42170edd6a95e4a`

Branch: `test/pirate-necromancy-gt-20260917`

Canonical test root: `G:/刷刷宝/Worktrees/pirate-necromancy-gt-20260917`

## Existing capability (source inspection, not live GT)

Dashboard test profile → `shell.test_profiles.apply_profile` → Dashboard settings UI collection/save → `RunnerService` → `execute_runtime_mediator` → `RuntimeMediator` → inherited policy assembly → `assemble_policy_settings`.

- `Settings.cards` order selects existing `choice_policy.json` advanced groups in order. `Settings.bonds` alone does not select advanced groups.
- Existing UI metadata already exposes both 海盗 and 亡灵. No new group definition is required.
- Pirate canonical group: 海盗 / 白赚海盗 / 海盗劫掠者 / 海盗宝藏.
- Necromancy canonical group: 亡灵 / 亡灵天灾 / 白骨复生 / 魂火收割 / 巫妖之躯.
- 藏宝图 starter is missing from the Pirate advanced group. The existing OCR dictionary canonical token is 藏宝图(三), with header aliases. Adding that token to test Settings.cards does not assert that every concrete card is physically number three.
- Existing group ordering is a policy priority/count contract, not proof of Pirate lifecycle completion or a correct warship→Necromancy handoff.
- 海盗宝藏 and guide/dictionary members without live frames remain unverified. Historical report has a 亡灵 header/亡灵天灾 card image, not this run's GT. Do not infer other members' mechanics from catalog presence.

## Chosen test profile

Name: 海盗+亡灵机制GT; schema_version: 1; mode_id: normal_farm.

- stage_targets: [1-12]
- auto_create_room: true
- new_room_every_times: false
- cycle_num: 1
- auto_reputation: false
- auto_secret_realm: true  (same-run post-game secret-realm GT via the official Settings path)
- cards: [zhufu, jj, 藏宝图(三), 海盗, 亡灵]
- bonds: [经济]
- attributes: []
- bond_must_take: [藏宝图(三)]
- bond_advanced_unlock_s: 60.0
- treasure_allow_negative: []
- skills: unchanged from operator selection.

60 seconds is a TEST PROFILE value, not live-calibrated production policy. Production policy remains ratio 0.8 / time fallback 480 seconds. Zero continues to mean no time fallback, not immediate unlock. Existing confidence, hard whitelist and capacity guards are not disabled.

## Minimum prototype boundary

The baseline profile schema cannot set bonds/attributes or a per-Settings time override; stale Dashboard shell selections can re-enter collected settings. The proposed isolated patch adds the narrow configuration contract and reconstructs profile UI state using existing metadata. No mediator testing conditional, new advanced-group table, scheduler, QUIT, room form, HUD gate or Harness baseline change is authorized.

Actual implementation and verification are recorded in the final validation report; this document describes the chosen contract, not a PASS claim.

## Runtime status

No game input issued. No unattended loop started. The provided desktop shortcut still targets the production launcher and has NOT been changed to this test root. Source-only checks are not desktop deployment or live GT.

Initial `diagnose_lobby.py` run returned 0 but emitted `ctypes.ArgumentError: OverflowError: int too long to convert` at `IsWindowVisible`; its zero candidates are invalid absence evidence. Independent visible-window listing returned 0 and showed no KK/Warcraft window; independent 1920×1080 PIL capture showed a terminal desktop. This establishes no available game surface, not absence of every possible hidden game process. Further environment diagnosis stopped. The raw desktop image remains local because it includes unrelated terminal sessions; do not push it.

No EX pill image was actually attached to this conversation. Existence/function is USER_CONFIRMED; screenshot file provenance is missing, not invented.
