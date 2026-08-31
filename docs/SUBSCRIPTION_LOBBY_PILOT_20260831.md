# Subscription-first Lobby Pilot — 2026-08-31

## Scope and evidence boundary

This pilot integrates ShuaBao with the normalized Subscription Lab contract without
embedding FOSSBilling, Keygen, or Keygate logic in the game FSM.

- Main-repo base: `8ce97eaacbeda48b7cac1b927f8bfacd8ae29e49`
- Subscription Lab contract baseline: `642235c85e9331c024b137d35d88aa3cf1c69cb1`
- Integration branch: `integration/subscription-lobby-pilot-20260831`
- Subscription Lab PR #1 remains Draft and MUST NOT be merged for this pilot.
- This branch is a Pilot. Do not merge it into the live-test branch until the local
  entitlement and lobby evidence below is complete.

`code wired`, automated/offline test PASS, and live business PASS are different facts.
A click, frame change, loading page, or successful HTTP request is not lobby business PASS.

## Subscription start boundary

The game runtime consumes only:

`POST /v1/entitlements/validate`

The check happens once in the shared LIVE worker body before `RuntimeMediator` is
constructed, before OCR preparation, and before any game input. There is no subscription
poll inside `Mediator.tick()`.

A subscription status change while a Worker is already running MUST NOT kill that Worker.
The next LIVE start performs the next authoritative validation.

Pilot configuration is environment-only:

- `SHUABAO_SUBSCRIPTION_MODE=off|shadow|enforce` (default `off`)
- `SHUABAO_SUBSCRIPTION_BASE_URL`
- `SHUABAO_SUBSCRIPTION_LICENSE_KEY`
- `SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT`
- `SHUABAO_SUBSCRIPTION_TIMEOUT_S` (optional; default 3s, clamped 0.5..10s)

No License Key or server secret is persisted in dashboard Settings. The Pilot device
fingerprint is an explicit test identity, not a claim that the production HWID collector
is complete.

### Policy

- `off`: zero network I/O; LIVE is unchanged.
- `shadow`: obtain the authoritative decision and log `would_allow`, but do not block LIVE.
- `enforce`: fail closed on missing config, transport failure, malformed response, or
  `can_start_runner != true`.

For the requested local subscription-first test, use `enforce` only after the local
license has been created and activated successfully.

## Local deployment sequence

### 1. Start the Subscription Lab stack

Use the Lab's committed compose/runbook at contract SHA `642235c...` and verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

The result must be healthy and backed by the intended Keygen provider. Do not use an
in-memory provider as evidence for the final local Pilot.

### 2. Create a long-lived local Pilot license

Provision the long-lived entitlement through the existing Subscription Lab provisioning
path. Do not add a client-side license-creation/admin API to ShuaBao.

Choose one stable Pilot identity for this machine, for example:

```powershell
$pilotFp = "shuabao-main-win-pilot-01"
```

This value is a Pilot binding only. Production hardware collection remains separate work.

### 3. Activate the Pilot device once

After a valid License Key exists:

```powershell
$bridge = "http://127.0.0.1:8000"
$license = "<LOCAL-PILOT-LICENSE-KEY>"
$pilotFp = "shuabao-main-win-pilot-01"

$activate = @{
  license_key = $license
  hardware = @{
    fingerprint = $pilotFp
    components = @{}
    platform = "windows"
    hostname = $env:COMPUTERNAME
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri "$bridge/v1/devices/activate" `
  -ContentType "application/json" `
  -Body $activate
```

Activation must be read back from the Subscription Lab/Keygen evidence. A local HTTP 200
alone is not enough if the upstream machine record is absent.

### 4. Validate before launching ShuaBao

```powershell
$validate = @{
  license_key = $license
  hardware = @{
    fingerprint = $pilotFp
    components = @{}
    platform = "windows"
    hostname = $env:COMPUTERNAME
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri "$bridge/v1/entitlements/validate" `
  -ContentType "application/json" `
  -Body $validate
```

Required result for the long-lived Pilot:

- `valid == true`
- `can_start_runner == true`
- status is an allowed state such as `ACTIVE` (or the Lab contract's `TRIAL`/`GRACE`)

### 5. Launch the rebuilt integration package in the same PowerShell

The source SHA changed after the previous `8ce97ea...` package. Rebuild from this
integration branch and verify the package `build_identity.source_sha` equals the final
branch HEAD before live testing.

Set process-only secrets and launch from the same shell:

```powershell
$env:SHUABAO_SUBSCRIPTION_MODE = "enforce"
$env:SHUABAO_SUBSCRIPTION_BASE_URL = $bridge
$env:SHUABAO_SUBSCRIPTION_LICENSE_KEY = $license
$env:SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT = $pilotFp
$env:SHUABAO_SUBSCRIPTION_TIMEOUT_S = "3"

# Launch the newly rebuilt ShuaBao package here.
```

Do not copy the License Key into JSON settings, source files, screenshots, bundles, or
Git logs.

## Entitlement acceptance tests

Before lobby input testing, record these separately:

1. `ACTIVE + enforce` -> LIVE reaches the normal runtime dependency preparation path.
2. Invalid/expired/revoked test entitlement + `enforce` -> `RuntimeMediator` is not created
   and there is zero game input.
3. Bridge unavailable + `enforce` -> fail closed, zero game input.
4. `shadow` + denied entitlement -> logs `would_allow=False` but does not block the Worker.
5. Start while ACTIVE, then change backend state while that Worker is running -> do not
   force-kill the running Worker; after a normal stop, the next start must honor the new
   entitlement state.

Only item 1 is needed before normal lobby LIVE evidence begins. Items 2-5 are contract and
safety acceptance for the integration branch.

## Lobby code status at the base SHA

### `follow_team`

Existing `FollowTeamSM` is intentionally a shortened path:

`already in team room -> wait host -> stage wait / in game -> back to same room`

It explicitly performs zero RoomStart / room creation / quick-join actions. This matches
"follow an existing convoy" but it currently does **not** contain a verified guest Ready
action.

### `lobby_hitch`

Existing `HitchSearchSM` already provides the search/recovery skeleton:

- room search constrained to the configured 3/4 prefix evidence;
- bounded attempts (`JOIN_ATTEMPTS=3`);
- bounded search window (`SEARCH_TIMEOUT_S=120`);
- pending join requires later room evidence before it is counted complete;
- kick/disband OCR markers reset toward lobby handling;
- exhausted search returns to lobby only with later lobby-page confirmation;
- after the configured sleep it resumes search instead of spinning inputs.

This is **code-wired**, not current-SHA live PASS.

## Missing Ready Ground Truth

The repository does not currently contain a separately verified guest `Ready` template /
state transition for these two passenger modes. Therefore this Pilot MUST NOT invent a
coordinate, reuse the host's RoomStart button, or treat "entered room" as Ready.

First live room visit should capture Ground Truth for:

1. passenger is definitely inside the intended room;
2. Ready button before click;
3. one deliberate human Ready click;
4. Ready-state visual after click;
5. host starts game and passenger reaches real game HUD.

Only after that evidence exists should production code add the smallest Ready action to
the existing room state handling. Do not add a second lobby FSM or a generic click/retry
watchdog.

## Live test order

### A. Follow-team smoke first

Precondition: the passenger account is already in the known convoy room.

Required chain:

`subscription ACTIVE -> start follow_team -> room identity confirmed -> Ready GT/action -> host starts -> real HUD`

PASS requires real HUD after the intended room. Waiting in a room, clicking Ready, or a
loading frame alone is not PASS.

### B. Lobby-hitch normal path

Required chain:

`subscription ACTIVE -> lobby -> refresh/search -> matching room -> join click -> later in-room confirmation -> Ready -> host starts -> real HUD`

The room match and the later in-room confirmation must be separate evidence.

### C. Lobby-hitch recovery cases

Run independently so each failure has an attributable bundle:

1. target room disappears / join fails -> no false in-room state -> continue bounded search;
2. passenger is kicked -> recognize kick evidence -> return to lobby -> continue search;
3. room is dissolved -> recognize dissolve evidence -> return to lobby -> continue search;
4. search exhausts 3 attempts or 120s -> GO_HOME -> later lobby confirmation -> sleep -> re-search.

A generic disconnect/retry modal is NOT included in these acceptance cases because
`disconnect_modal_missing` still lacks real Ground Truth.

## PASS boundary

The integration is ready to merge only after all of the following are independently true:

- Subscription automated tests green on the integration HEAD.
- Rebuilt local package identity matches that HEAD.
- Long-lived local Pilot entitlement is ACTIVE and machine activation is read back.
- `enforce` allow and deny paths demonstrate zero ambiguity about whether a Worker may
  reach RuntimeMediator.
- Guest Ready Ground Truth is captured and the minimal production Ready action is wired.
- Follow-team reaches real HUD from an already-existing convoy room.
- Lobby-hitch reaches real HUD through search -> join -> Ready.
- At least one real join-failure or kick/disband case demonstrates bounded return-to-search.

Until then keep the integration PR Draft and do not merge.
