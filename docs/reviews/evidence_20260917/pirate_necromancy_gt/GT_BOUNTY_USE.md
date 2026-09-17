# GT — Bounty Order (悬赏令) Use — 2026-09-17

- Starting SHA: `5b0f2436c5fe8ec2057f4266f42170edd6a95e4a`
- Branch: `test/pirate-necromancy-gt-20260917`
- Mode: `MANUAL_GT` (human-operated GT). This round **executed: false**.
- Overall: **NOT_RUN / BLOCKED at preflight**

## Preflight context

No game window detected (see `GT_PIRATE_STARTER.md` preflight section and `preflight/` artifacts). Detection stopped; nothing launched, no input sent. All bounty interactions therefore unexecuted.

## Tier policy contract (USER_CONFIRMED, from OWNER_CONFIRMED_RULES.md)

Lowest sufficient tier, mapping target rarity → bounty color:

| Target rarity | Bounty tier |
|---|---|
| UR | Red (红) |
| SSR | Orange (橙) |
| SR | Purple (紫) |
| R | Blue (蓝) |
| N | Green (绿) |

## Planned scenarios (never executed)

1. **Same-tier bounty** (同档): NOT_RUN — no UI, no target panel, no before/after count.
2. **No legal target** (无合法目标): NOT_RUN — no observation of the resulting state or messaging.
3. **Lowest-sufficient-tier use**: NOT_RUN per the table above. Interaction UI, target selection, consumption and count changes still need live evidence.

## Constraints

- Do not actively test higher-tier substitution without a naturally safe opportunity (owner restriction).
- A single LMB consumption from bag was NOT executed — see `GT_BAG_CONSUMABLE.md`.
- Historical source: branch `docs/mechanics-contract-20260917` — cited only.

## NOT_OBSERVED

UI panels, target list, OCR raw, before/after bounty counts, any consumption animation or confirmation.

## Result

All bounty scenarios NOT_RUN. No AUTO PASS claimed.
