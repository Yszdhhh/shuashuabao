# Reborn WoW screenshot library

This directory preserves the user-supplied screenshots as immutable full-screen evidence. It is deliberately separate from the existing P0-B replay manifest until each action has a real detector and dry-run test.

## Categories

| Directory | Contents | Intended use |
| --- | --- | --- |
| `room/` | Host room waiting page | Detect room-ready state and the `开始游戏` action. |
| `stage/` | Chapter 1 and Chapter 2 stage-selection pages | Detect visible stage rows; visible rows depend on account unlock state. |
| `main_line/` | Main-line play with challenge auto disabled/enabled | Verify the four lower-left challenge cards transition to green `自动`. |
| `choices/` | Skill, bond, treasure, and Black Merchant evidence | Classify modal types before any choice policy is implemented. |
| `endgame/` | Victory, archive challenges, NPC hub, heirloom challenge, Great Rift confirmation | Drive the post-victory challenge sequence. |

`manifest.json` is the machine-readable catalog. It records state names, verified user rules, safe default actions, dimensions, and SHA-256 checksums.

## Verified behavior rules

- **Exit game:** in every in-game state, the intentional exit target is the top-left `退出游戏` button. It must never be used as a recovery guess.
- **Challenge auto:** the lower-left gold, wood, experience, and treasure challenge cards are enabled by hover + right click. A green `自动` label is the required post-click confirmation.
- **Archive challenges:** click each visible, unlocked archive challenge. Do not click locked cards or assume a fixed number of cards.
- **Boss selection:** default to the last visible enabled boss. A configured boss overrides that default.
- **Heirloom challenge:** open it from the NPC hub, then select the configured or last visible enabled boss. In the boss dialog, left click starts a challenge and right click only opens loot details.
- **Great Rift:** right click the Great Rift NPC only after all map challenges are complete, no active boss remains, and the upper-left `英雄挑战` indicator is visible. Then left click `是` in the confirmation dialog. If `英雄挑战` is absent, do not attempt Great Rift.
- **Choice modals:** the current evidence has three choices. Skill, bond, and treasure policies must be configured before real input; four- and five-choice layouts require their own screenshots before they are accepted.

## Reference-only legacy material

`C:\Users\10639\Desktop\🎮 影音游戏\1.3.8\Images` contains historical templates whose names match the current flow: `continueGame`, `archiveChallenge`, `cjbtiaozhan`, `damijing`, `mijingOk`, `HeroChallenge`, `quit`, and `gameDisconnect`, plus boss image libraries. They are useful for naming and regression comparison only. The current screenshots in this directory remain the source of truth because UI layout and assets can change between versions.

## Evidence still needed

- A current-version full-screen disconnect/exit confirmation modal for the P0-B required gate.
- A full-screen Black Merchant state; the current `black_merchant_card_strip.png` is only a local crop.
- A four-choice and a five-choice skill-selection modal when the account exposes them.
- The current account's actual target-stage page when a real runtime target is chosen (for example, `4-2` if that is the desired configured target).
