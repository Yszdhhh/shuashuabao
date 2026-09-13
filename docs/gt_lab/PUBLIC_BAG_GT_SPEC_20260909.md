# PUBLIC BAG GT SPECIFICATION (2026-09-09)

## 1. Feature Priority & Context

- **Priority**: Rank-1 highest priority new feature for ShuaBao hitch operations.
- **Goal**: Automatically transfer critical team resources (Devour Pills and Green Talismans) from personal bag into team public bag during `lobby_hitch` sessions without accidental consumption or grid misplacement.

## 2. Product Ground Truth & Input Safety Contract

### 2.1 Target Item Criteria
Under `lobby_hitch` mode, the following items MUST be deposited into the Public Bag:
1. **吞噬丹 (Devour Pill)**: Identified via template / icon matching (`danGif.png` / `pill_bag`).
2. **绿色神符 (Green Talisman)**: Green item rarity band AND OCR text match in choice lexicon talisman list.

### 2.2 Input Safety Invariant (Crucial)
- **PERSONAL SOURCE ITEM**: **RIGHT CLICK ONLY** (`act_right_click`).
- **STRICT PROHIBITION**: **NEVER LEFT CLICK PERSONAL SOURCE ITEMS**. Left-clicking in the game immediately consumes/uses the item (e.g., swallows the pill or activates the talisman), permanently destroying the team asset.

### 2.3 Step-by-Step Operation Contract
```
[1. Source Confirm]   fresh-confirm source item existence & slot index in personal inventory
         ↓
[2. Source Select]    RIGHT CLICK source item (selects/attaches item for deposit)
         ↓
[3. Open Bag View]    Press 'B' (or click bag toggle) if public bag view not visible
         ↓
[4. Bag Page Confirm] fresh-confirm BAG PAGE presence
         ↓
[5. Public Bag Check] fresh-confirm PUBLIC BAG container presence
         ↓
[6. Empty Slot Locate]Scan and identify verified PUBLIC_BAG_EMPTY_SLOT
         ↓
[7. Deposit Click]    LEFT CLICK target public empty slot
         ↓
[8. Post-Confirm]     fresh-confirm item transfer (public slot occupied, personal slot cleared)
```

## 3. Ground Truth Label Taxonomy

| Label | Definition / Criteria |
|---|---|
| `PERSONAL_BAG` | Bounding box of the player's private inventory container. |
| `PUBLIC_BAG` | Bounding box of the team-shared public bag container. |
| `PUBLIC_BAG_EMPTY_SLOT` | Available, unlocked, unoccluded deposit slot inside the public bag. |
| `PUBLIC_BAG_OCCUPIED_SLOT` | Public slot already containing an item (invalid for deposit). |
| `SOURCE_DEVOUR_PILL` | Identified Devour Pill item in player inventory. |
| `SOURCE_TALISMAN` | Identified Green Talisman item in player inventory. |
| `SOURCE_SELECTED` | Item attached to cursor/drag state following a right-click. |
| `DEPOSIT_REQUESTED` | Left-click dispatched on verified public empty slot. |
| `DEPOSIT_CONFIRMED` | Fresh frame confirms source item now occupies the target public slot. |
| `PUBLIC_BAG_FULL` | Zero empty slots detected in public container; triggers deposit abort. |

## 4. Hard Negatives Specification

The GT training and test fixtures MUST include the following hard negative classes:
1. `PERSONAL_BAG_EMPTY_SLOT`: Empty slot in private bag (must never be clicked as deposit target).
2. `PERSONAL_BAG_OCCUPIED_SLOT`: Unrelated private items (weapons, armor, gold).
3. `PUBLIC_BAG_OCCUPIED_SLOT`: Slots in public bag with items (clicking will swap or fail).
4. `DARK_UNUSABLE_SLOT`: Locked or disabled public bag slots.
5. `SELECTED_HIGHLIGHTED_SLOT`: Slots with hover or selection glow affecting template match.
6. `PANEL_BORDER`: Metal frame and dividers of the backpack windows.
7. `TOOLTIP`: Pop-up item descriptions obscuring slot bounding boxes.
8. `ANIMATION_FRAME`: Slot transition frames during bag opening or item transfer.

## 5. Coordinate Calculation Invariant

- **FORBIDDEN**: Hardcoded global absolute coordinates (e.g., `(1455, 602)`).
- **MANDATORY**: Coordinates MUST be mathematically derived from:
  $$\text{Slot}(r, c) = \text{BBox}_{\text{panel}}.\text{origin} + \text{Margin} + [c \times \text{Step}_X, r \times \text{Step}_Y]$$
  This guarantees robustness against window repositioning and DPI scaling.

## 6. Solo Video Boundary & Test Readiness

- **Current Assets**: Desktop solo/challenge video recordings (`20260826_230425.mp4`, `20260826_230921.mp4`).
- **Permitted Verifications in Current Phase**:
  - `PUBLIC_BAG_LAYOUT_GT`
  - `SOURCE_RIGHT_CLICK_GT`
  - `B_OPEN_GT`
- **Explicit Boundary**: Solo videos **CANNOT** declare `PUBLIC_BAG_DEPOSIT_GT = PASS` due to absence of live multiplayer network sync.
- **Tooling**: `tools/gt_lab/extract_bag_gt.py` is configured and ready for frame slicing upon receipt of multiplayer hitch recordings.
