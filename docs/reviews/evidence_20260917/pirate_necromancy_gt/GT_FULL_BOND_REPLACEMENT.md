# GT — Full Bond Bar Replacement — 2026-09-17

- Starting SHA: `5b0f2436c5fe8ec2057f4266f42170edd6a95e4a`
- Branch: `test/pirate-necromancy-gt-20260917`
- Mode: `MANUAL_GT` (human-operated GT). This round **executed: false**.
- Overall: **NOT_RUN / BLOCKED at preflight**

## Preflight context

No game window detected; detection stopped, nothing launched, no input sent (see `preflight/` artifacts).

## Owner-confirmed rule (not retested)

Full bond bar requires replacement when the new card cannot safely release capacity before placement. This automation has not previously closed successfully (USER_CONFIRMED).

Combine releases occupied component slots after completing the combination (USER_CONFIRMED). **A (合成释放) is already confirmed; this GT does not retest it.**

## Planned B-path observations (never executed)

When the bar is full and a new card cannot safely release capacity before placement:

1. Replacement UI appearance
2. Slot selection
3. Cancel path
4. Secondary confirmation
5. Timeout behavior

All five: **NOT_RUN / NOT_OBSERVED**.

## NOT_OBSERVED

Replacement UI, slot highlights, cancel control, secondary-confirm dialog, timeout timer, occupancy before/after.

## Historical source

Branch `docs/mechanics-contract-20260917` — cited only, not new live GT.

## Result

Full-bar replacement UI/slots/cancel/confirm/timeout all NOT_RUN. No AUTO PASS claimed.
