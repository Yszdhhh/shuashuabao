#!/usr/bin/env python3
"""Print a safe, read-only snapshot of the L0/L1 lobby decision inputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.mediator import Mediator, Phase  # noqa: E402
from gamescript.settings import Settings  # noqa: E402
from gamescript.vision.capture import (  # noqa: E402
    L0_WINDOW_KEYWORDS,
    L1_WINDOW_KEYWORDS,
    capture_target,
    find_window_targets,
)


def _save_frame(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", frame.bgr)
    if not ok:
        raise RuntimeError(f"cannot encode screenshot: {path}")
    encoded.tofile(str(path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config" / "default_settings.json"))
    parser.add_argument(
        "--save-dir",
        default="",
        help="optional directory for diagnostic screenshots; omit to keep the run read-only",
    )
    args = parser.parse_args()

    settings = Settings.load(args.config)
    mediator = Mediator(settings, ROOT)
    print(
        "settings "
        f"auto_create_room={settings.auto_create_room} "
        f"game_mode={settings.game_mode} "
        f"dry_run={settings.dry_run} "
        f"stage={settings.stage1}/{settings.stage2} "
        f"targets={settings.stage_targets or '-'} "
        f"threshold={settings.match_threshold}"
    )

    save_dir = Path(args.save_dir) if args.save_dir else None
    targets_by_role = [
        ("l0", settings.window_title_contains + "," + ",".join(L0_WINDOW_KEYWORDS)),
        ("l1", settings.window_title_contains or ",".join(L1_WINDOW_KEYWORDS)),
    ]
    for role, title in targets_by_role:
        targets = find_window_targets(title, role=role)
        print(f"role={role} candidates={len(targets)} title_query={title!r}")
        for index, target in enumerate(targets):
            frame = capture_target(target)
            context = mediator._detect_context(frame, role)
            values = {
                "hwnd": target.hwnd,
                "title": target.title,
                "frame": f"{frame.width}x{frame.height}@({frame.left},{frame.top})",
                "context": context,
            }
            if role == "l0":
                values.update(
                    room_start=bool(mediator._find_room_start(frame)),
                    map_create=bool(mediator._find_map_create_room(frame)),
                    create_confirm=bool(mediator._find_create_confirm(frame)),
                )
            else:
                values.update(
                    stage_page=mediator._find_stage_page(frame),
                    stage_start=bool(mediator._find_stage_start(frame)),
                    in_game=bool(
                        mediator.find_scene(frame, "card_panel")
                        or mediator.find_scene(frame, "skill_panel")
                    ),
                )
            print("  " + " ".join(f"{key}={value!r}" for key, value in values.items()))
            if save_dir is not None:
                path = save_dir / f"{role}_{index}_{target.hwnd}.png"
                _save_frame(frame, path)
                print(f"  screenshot={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
