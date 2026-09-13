# MERCHANT REFRESH 3-STATE GT SPECIFICATION (2026-09-09)

## 1. Context & Motivation

- **Background**: In ShuaBao production, `MerchantFSM` (policy/merchant_fsm.py) currently fail-opens on refresh timeouts when `purchases == 0`, potentially cycling through up to 20 rerolls even when the merchant stock has stalled or player gold is insufficient.
- **Goal**: Establish a mathematically grounded, 3-state Ground Truth verification contract for Black Merchant slot refresh actions before modifying production code.

## 2. The 3-State Taxonomy

| State Label | Physical Definition | Required Downstream FSM Behavior |
|---|---|---|
| `MERCHANT_REFRESH_MUTATED` | Fresh frame confirms pixel diff in goods ROI $\ge 5\%$ (or slot occupancy/item target fingerprint changed). | Refresh accepted as physically occurred. Transition to `CONFIRMING -> READY`. |
| `MERCHANT_REFRESH_UNCHANGED` | Goods ROI pixel diff $< 5\%$ across consecutive healthy frames following refresh input. | Refresh had no visible effect (e.g., resource exhausted, button miss, cooldown). Accumulate `unchanged_streak`. |
| `MERCHANT_REFRESH_SAMPLE_FAILED` | Frame capture unhealthy: black frame ($\mu < 2.0$), low entropy ($\sigma < 1.0$), resolution mismatch, or occluding modal detected. | **CRITICAL INVARIANT**: **NEVER categorize as UNCHANGED**. Discard sample, wait for visual recovery, do not increment failure streaks. |

## 3. Core Architectural Rule: Pixel Mutation Role

1. **Mutation as Auxiliary / Negative Evidence**:
   - Pixel mutation CAN prove that a refresh visually took place.
   - Pixel mutation **CANNOT** prove business success on its own (e.g., an animated particle or cursor movement over the slots is not an item change).
   - Therefore: **Pixel Changed $\neq$ Business Success**. Template & OCR identity must confirm actual target item acquisition.
2. **Sample Failure Isolation**:
   - If DaMo / OpenCV sampling fails or encounters corrupted memory, the system MUST return a safe sentinel (analogous to Competitor 3's `999` changed points) to prevent false "out of resources" eviction.

## 4. Bounded Stop Evidence Evaluation (Competitor 3 Inspiration)

- **Competitor 3 Mechanism**:
  - In `buy_baowushuaxin_from_market@9725`: if the same item at the same position exists after 3 consecutive clicks $\rightarrow$ infer resource exhausted $\rightarrow$ stop.
  - In `trigger_pill_emergency_pipeline@9653`: if 2 consecutive 'H' presses produce zero pixel change $\rightarrow$ enter 10s cooldown.
- **ShuaBao Transfer Evaluation**:
  - For ShuaBao `MerchantFSM`, we evaluate introducing:
    $$\text{If } \text{unchanged\_streak} \ge 2 \implies \text{Phase} = \text{EVICTED (or Cooldown)}$$
  - This replaces the current blind behavior of burning the entire 20-reroll budget when gold is exhausted.
  - **Gate Rule**: This logic must be validated against `MERCHANT_REFRESH_MUTATED` / `UNCHANGED` GT fixtures before touching `src/shuabao/policy/merchant_fsm.py`.

## 5. Tooling & GT Collection Harness

- **Verification Tool**: `tools/gt_lab/extract_merchant_gt.py`
  - Computes `calculate_roi_mutation(before, after, roi_rect, threshold=0.05)`.
  - Automatically isolates unhealthy frames as `MERCHANT_REFRESH_SAMPLE_FAILED`.
- **Collection Protocol**:
  - Capture pairs: `before_H.png` and `after_H.png` with timestamp metadata.
  - Required test cases:
    1. Successful refresh with stock change.
    2. Zero-gold refresh attempt (true unchanged).
    3. Transition animation frame (hard negative).
    4. Occluded window frame (sample failed).
