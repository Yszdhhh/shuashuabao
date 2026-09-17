# GT — Bag Consumables (丹 / 悬赏令 single LMB) — 2026-09-17

- Starting SHA: `5b0f2436c5fe8ec2057f4266f42170edd6a95e4a`
- Branch: `test/pirate-necromancy-gt-20260917`
- Mode: `MANUAL_GT` (human-operated GT). This round **executed: false**.
- Overall: **NOT_RUN / BLOCKED at preflight**

## Preflight context

No game window detected; detection stopped, nothing launched, no input sent (see `preflight/` artifacts and `GT_PIRATE_STARTER.md`).

## Planned action (never executed)

Open bag, locate pill (丹) and bounty order (悬赏令) items, perform a **single left-click** on each, observe the consumption effect.

## NOT_OBSERVED

- Bag UI, item slots, tooltips
- OCR raw / item counts before and after
- Effect of single LMB on pill or bounty order

## Owner-confirmed constraints governing future execution

- Normal pill devours randomly; automation controls *when* to use, never *which* card is devoured (USER_CONFIRMED). No automatic use with Pirate starter, advanced-group key card, nearly complete stack, or owner-protected card present — unknown identity cannot establish safety.
- EX pill (神级吞噬丹) devours EX cards (USER_CONFIRMED). A screenshot of the EX pill was reported previously but **was never actually received in this conversation (MISSING_ATTACHMENT)**. No matcher, template, or image-based rule may be fabricated from it; USER_SCREENSHOT provenance stays pending recovery of the actual file.
- Z routing (USER_CONFIRMED): available HUD item slot → HUD first; full HUD item bar → bag. Postcondition: natural opportunities for this GT this round = 0.

## Historical source

Branch `docs/mechanics-contract-20260917` — cited only, not new live GT.

## Result

Bag consumption NOT_RUN. No AUTO PASS claimed.
