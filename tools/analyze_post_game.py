#!/usr/bin/env python3
"""P1-B0 read-only post-game evidence analyzer.

For every screenshot under fixtures/reborn_wow/endgame this tool reports:
  1. frame health and the mediator's current page classification;
  2. which registered scene anchors (current assets) match the page;
  3. which legacy 1.3.8/Images anchors match the page (direct evidence);
  4. the exact input the current mediator WOULD produce on that page
     (dry-run simulation; no real input is ever sent);
  5. an evidence verdict: CONFIRMED / INFERRED / UNKNOWN.

The tool never clicks, never writes, and never alters any fixture.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.vision.capture import Frame, check_frame_health
from shuabao.vision.matcher import match_any
from shuabao.vision.stage_selector import visible_stage_rows

ENDGAME_DIR = ROOT / "fixtures" / "reborn_wow" / "endgame"
# Legacy 1.3.8 images are external reference material; resolved below when reachable.
LEGACY_138_DIR = ROOT.parent / "1.3.8" / "Images"

LEGACY_ANCHORS = [
    "continueGame",
    "archiveChallenge",
    "cundang",
    "cundangInfo",
    "tuanben",
    "cjbtiaozhan",
    "cjbBoss",
    "cjbBossbak",
    "sgzxBoss",
    "boosIcon",
    "damijing",
    "mijingOk",
    "HeroChallenge",
    "quit",
    "gameDisconnect",
    "retryConnect",
    "woodSuccess",
    "mainIdentifier",
]

SCENE_CHAIN = [
    "archive",
    "boss_entry",
    "longzhu",
    "secret",
    "disconnect",
    "fail",
    "ok",
    "close",
    "env_anchor",
]


def load_frame(path: Path) -> Frame | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return None
    return Frame(img, window_title="英雄三国KK", hwnd=10001)


def replay_sim(med: Mediator, frame: Frame, context: str) -> tuple[str, tuple[int, int] | None]:
    """Replicate tools/run_replay.py's action-branch logic for a fixture entry.

    Returns (action_name, click_point). The replay runner does NOT apply the
    mediator's Fail-Closed scene gates, so this sim exposes what a root-manifest
    fixture with this expected_state would produce.
    """
    if context in ("MAIN_LINE", "IN_GAME"):
        if med._selection_anchor(frame):
            choice = med._find_reward_choice(frame)
            if choice:
                kind, hit = choice
                return "SelectSkill", hit.center
            return "none", None
        toggle = med._find_auto_task_toggle(frame)
        if toggle:
            return "EnableAutoTask", toggle.center
        for scene_key in ("coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge"):
            found = med._find_challenge_button(frame, scene_key)
            if found:
                label_hit, click_hit = found
                if not med._challenge_is_auto(frame, label_hit):
                    return "EnableAutoChallenges", click_hit.center
        return "none", None
    return "none", None


def would_act(med: Mediator, frame: Frame) -> list[str]:
    """Simulate the mediator's main-line decision chain; collect would-be inputs."""
    acts: list[str] = []
    post_game = med._post_game_state(frame)
    if post_game:
        if post_game == "POST_VICTORY":
            acts.append("POST_VICTORY: would LEFT-CLICK continueGame (ContinueGame)")
        else:
            acts.append(f"Fail-Closed stop ({post_game}) - no input")
        return acts
    if med.find_scene(frame, "archive"):
        acts.append("Fail-Closed stop (archive) - no input")
        return acts
    if med.find_scene(frame, "boss_entry"):
        acts.append("Fail-Closed stop (boss_entry) - no input")
        return acts
    if med.find_scene(frame, "longzhu"):
        acts.append("Fail-Closed stop (longzhu) - no input")
        return acts
    if med.find_scene(frame, "secret"):
        acts.append("Fail-Closed stop (secret) - no input")
        return acts
    if med._selection_anchor(frame):
        choice = med._find_reward_choice(frame)
        acts.append(f"selection anchor: {'choice=' + choice[1].name if choice else 'zero-action wait'}")
        return acts
    if med._is_auto_task_enabled(frame):
        acts.append("auto task ON: zero action")
    elif med._find_auto_task_toggle(frame):
        acts.append("auto task OFF: would LEFT-CLICK toggle")
    for key, label in (
        ("coin_challenge", "金币"),
        ("wood_challenge", "木材"),
        ("experience_challenge", "经验"),
        ("treasure_challenge", "宝物"),
    ):
        found = med._find_challenge_button(frame, key)
        if not found:
            continue
        label_hit, click_hit = found
        state = med._resolve_challenge_state(frame, label_hit)
        if state.name == "OFF":
            acts.append(f"{label}挑战 OFF: would RIGHT-CLICK @ {click_hit.center}")
        elif state.name == "ON":
            acts.append(f"{label}挑战 ON: zero action")
        else:
            acts.append(f"{label}挑战 {state.name}: zero action")
    if visible_stage_rows(frame, med.images):
        acts.append("stage rows visible: would consider stage select")
    return acts


def main() -> int:
    med = Mediator(Settings(), ROOT)
    med.set_phase(Phase.MAIN_LINE, "post-game analysis")

    screenshots = sorted(ENDGAME_DIR.glob("*.png")) + sorted(ENDGAME_DIR.glob("*.jpg"))
    if not screenshots:
        print(f"No endgame screenshots under {ENDGAME_DIR}")
        return 1

    summary: list[dict] = []
    for shot in screenshots:
        frame = load_frame(shot)
        if frame is None:
            print(f"{shot.name}: READ ERROR")
            summary.append({"id": shot.stem, "error": "read error"})
            continue

        health = check_frame_health(frame)
        context = med._detect_context(frame)
        acts = would_act(med, frame)

        print("=" * 100)
        print(f"FILE: {shot.name}  ({frame.width}x{frame.height})")
        print(f"  health: {'OK' if health.is_healthy else health.details}")
        print(f"  context: {context}")

        hits: list[tuple[str, float, tuple[int, int]]] = []
        for scene_key in SCENE_CHAIN:
            hit = med.find_scene(frame, scene_key, threshold=0.55)
            if hit:
                hits.append((scene_key, hit.score, hit.center))
        anchor = med._selection_anchor(frame)
        if anchor:
            hits.append(("selection_anchor", anchor.score, anchor.center))
        stage_page = med._find_stage_page(frame)
        if stage_page:
            hits.append(("stage_page", 1.0, (0, 0)))

        # Legacy 1.3.8 direct pass
        legacy_138_dir = LEGACY_138_DIR
        if legacy_138_dir.is_dir():
            for name in LEGACY_ANCHORS:
                tmpl = legacy_138_dir / f"{name}.png"
                if not tmpl.is_file():
                    continue
                hit = match_any(frame, legacy_138_dir, [name], threshold=0.55, scales=(0.9, 1.0, 1.1))
                if hit:
                    hits.append((f"legacy:{name}", hit.score, hit.center))

        if hits:
            print("  anchor matches:")
            for name, score, center in sorted(hits, key=lambda h: -h[1]):
                print(f"    {name:24s} score={score:.3f} @ {center}")
        else:
            print("  anchor matches: NONE")

        print("  would-be inputs:")
        if acts:
            for a in acts:
                print(f"    - {a}")
        else:
            print("    - none (zero input)")

        replay_action, replay_click = replay_sim(med, frame, context)
        post_game = med._post_game_state(frame)
        evidence = "CONFIRMED" if any(h[1] >= 0.70 for h in hits) else ("INFERRED" if hits else "UNKNOWN")
        print(f"  multi-anchor classifier: {post_game}")
        print(f"  replay-sim (expected_state={context}): action={replay_action} click={replay_click}")
        print(f"  verdict: {evidence} | would_click={any('CLICK' in a for a in acts)}")

        summary.append(
            {
                "id": shot.stem,
                "resolution": [frame.width, frame.height],
                "health": health.is_healthy,
                "context": context,
                "evidence": evidence,
                "anchor_hits": [{"name": n, "score": round(s, 3), "center": list(c)} for n, s, c in hits],
                "would_inputs": acts,
                "would_click": any("CLICK" in a for a in acts),
                "post_game_state": post_game,
                "replay_action": replay_action,
                "replay_click": replay_click,
            }
        )

    print("=" * 100)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
