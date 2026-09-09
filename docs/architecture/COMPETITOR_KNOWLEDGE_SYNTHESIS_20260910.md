# Competitor Knowledge Synthesis (2026-09-10)

## 1. Executive Summary

A comprehensive, multi-subject investigation of all reverse-engineering and static-analysis assets was conducted across:
`C:\Users\10639\Desktop\竞品\拆解资产落库\`
Covering:
- **01_参考脚本1更新**: C# / .NET Decompiled assembly (`GameScript.Core`, `GameScript.Jobs`, `AutoJob.cs`, `LongzhuJob.cs`)
- **02_参考脚本3**: Python-based automation with extensive transfer maps (`COMP3_TO_SHUABAO_TRANSFER_MAP.md`, OCR benchmarks, asset catalogs)
- **03_参考脚本2**: AutoHotkey / compiled binary framework with state machine rules

---

## 2. Problem-Domain Competitor Evaluation Matrix

| Problem Domain | Competitor Pattern | ShuaBao Current Baseline | Comparative Evaluation | Recommendation & Action |
| :--- | :--- | :--- | :--- | :--- |
| **Capture Backend** | Comp 1: GDI BitBlt on desktop DC; Comp 3: Window DC BitBlt | ShuaBao: Windows GDI / PrintWindow fallback | **ALREADY BETTER** | ShuaBao isolates client rect correctly; PrintWindow handles occlusion. Maintain current backend. |
| **OCR & Preprocessing** | Comp 3: Raw crop + EasyOCR + 2x resize; Comp 1: Hardcoded template match for numbers | ShuaBao: PaddleOCR / rapid OCR with OpenCV preprocessing | **ADAPT** | Comp 3 benchmark proved 2x cubic interpolation boosts Chinese game font recognition from 68% to 92%. Adapt preprocessing pipeline without replacing model. |
| **Template Matching** | Comp 1: Exact RGB pixel matching; Comp 3: Grayscale normalized cross correlation (`cv2.matchTemplate`) | ShuaBao: Normalized CC with confidence thresholds (0.75-0.85) | **ALREADY BETTER** | ShuaBao handles DPI variations much better. Comp 1 pixel match is fragile. |
| **Input Generation** | Comp 1: PostMessage / SendMessage to HWND; Comp 3: pyautogui / SendInput | ShuaBao: 64-bit aligned Win32 SendInput | **ALREADY BETTER** | PostMessage is blocked by modern game anti-cheat and UIPI. SendInput with elevation is required. |
| **Thread & Lifecycle** | Comp 1: Nested while-loops with `Thread.Sleep`; Comp 3: Flat polling loop with timeout counters | ShuaBao: Unified `Mediator` tick loop + FSM | **ALREADY BETTER** | ShuaBao's state machine avoids thread lockups. |
| **Watchdog & Stagnation**| Comp 1: External process killer; Comp 3: Loop iteration counter resetting to initial state | ShuaBao: Wall-clock watchdog timer resetting phase | **ADAPT** | Competitor resets to a clean known state on stuck iteration. ShuaBao needs *Business Progress Token* rather than ticking heartbeat. |
| **Merchant & Refresh** | Comp 3: Pre-recorded slot ROI, compare hash before/after refresh | ShuaBao: Dynamic slot scanning, purchase confirmation latch | **ADAPT** | Comp 3's pre-refresh hash snapshot prevents ambiguous double-purchases when network lags. |
| **Public Bag / Transfer**| Comp 1: Blind right-click inventory sequence; Comp 3: Mouse drag with fixed coordinates | ShuaBao: Target state machine (in design) | **REJECT** | Both competitor approaches are blind clicks prone to dropping items or throwing away gear. Must use verified Right-Click + Slot Verification. |
| **Disconnection & Kick** | Comp 1: Wait 60s, restart client; Comp 3: Detect popup, click OK, re-enter room | ShuaBao: Dedicated `lobby_hitch.py` state machine | **ALREADY BETTER** | ShuaBao detects platform modal and kick events gracefully. |
| **Asset Organization** | Comp 1: Embedded binary resources; Comp 3: Subdirectory per scene (`lobby`, `battle`, `settlement`) | ShuaBao: `assets/Images/` flat structure | **ADAPT** | ShuaBao has 160+ flat PNGs. Comp 3's scene-based categorization simplifies ROI filtering. |

---

## 3. Deep Dive: Why Do Competitors Appear "Durable"?

When observing competitor scripts in production, users often remark that they appear "resilient" or "hard to kill". Our decompilation and static analysis reveal the truth behind this perception:

1. **Aggressive Coercive Recovery (Not True Robustness)**:
   In `AutoJob.cs` (Comp 1) and Comp 3 scripts, when any unrecognized UI state persists for > 5 seconds, the script performs:
   `SendKeys("{ESC}")` $\times 3$ → `Click(Known_Lobby_Anchor)` → Restart loop.
   *Verdict*: This is not architectural robustness; it is blind hammering. If the game is in an irreversible dialogue (e.g. equipment upgrade), pressing ESC or clicking lobby can destroy items.
2. **Fixed Anchor Fingerprints**:
   Competitors rely on 2 or 3 universal "safe zones" (e.g., top-left avatar, bottom-right bag button) to re-ground their coordinate frame.
   *Transferable Insight*: ShuaBao should adopt **anchor verification** before issuing multi-step actions, but reject blind ESC spamming.

---

## 4. Top 10 Transferable Patterns (What to Adapt)

1. **Pre-Action / Post-Action Hash Fingerprinting**: Snapshot slot pixels before clicking "Refresh" or "Buy"; if hash does not change within 200ms, mark outcome as `AMBIGUOUS` rather than assuming success.
2. **2x Cubic Interpolation for Short Chinese Game Fonts**: Upscale small OCR crops (e.g., "神符", "传家宝") by 200% using `INTER_CUBIC` prior to OCR inference.
3. **Bound Stagnation Recovery**: Cap consecutive recovery attempts to 3. If 3 consecutive recoveries fail, elevate to operator pause rather than looping infinitely.
4. **Scene-Local Coordinate Offsets**: Reference buttons relative to their containing dialog box header rather than global screen coordinates.
5. **Cooldown Intervals on UI Retries**: Enforce minimum 150ms delay between repeated clicks to avoid triggering OS double-click handlers.
6. **Passive Progress Heartbeat**: Distinguish loop execution (tick) from genuine game advancement (round completion).
7. **Clean Generation Invalidation**: On HWND change, discard all cached OCR and template coordinates immediately.
8. **Shadow Authorization Kernel**: Prevent accidental left-clicks on protected inventory slots.
9. **Unified Outcome Verification**: Return `CONFIRMED_SUCCESS`, `CONFIRMED_NO_EFFECT`, or `AMBIGUOUS` from all interaction helpers.
10. **Runtime Identity Handshake**: Launcher verifies running binary hash against `build_identity.json`.

---

## 5. Top Competitor Anti-Patterns (What to Reject Forever)

1. **Blind Coordinate Clicking**: Clicking $(X, Y)$ without verifying that the target modal is visible.
2. **Infinite While-True Loops with No Timeout**: Blocking the entire thread waiting for an image.
3. **Aggressive ESC Spam**: Sending ESC blindly, which closes crucial reward and victory panels prematurely.
4. **Assuming Success on Timeout**: Treating an expired wait as "the action probably worked".
5. **Multiple Concurrent Input Owners**: Background threads independently calling click helpers without central arbitration.
6. **Pixel Mutation as Business Proof**: Assuming that any screen change implies the specific requested action succeeded.
