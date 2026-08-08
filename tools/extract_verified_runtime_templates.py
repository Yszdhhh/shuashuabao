"""Rebuild exact UI templates from tracked full-screen evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]

SOURCES = {
    "exit": (
        ROOT / "fixtures" / "live_postgame_20260808" / "live_exit_confirm.png",
        "e20456c8499f56376b9c5ec3acd5c1f40a630edca2b791ea64c00938b1f38395",
    ),
    "archive": (
        ROOT / "fixtures" / "replay" / "archive_challenge_panel.png",
        "2e5fba81d1b1343ad88cd67c9780464cfed54473d441f8be511693a6114957f4",
    ),
    "stage": (
        ROOT / "fixtures" / "live_postgame_20260808" / "live_stage_select.png",
        "c46d86a1edbcfe05d85029c34ebc49e9bd6a097e4b4d0013027b8e56419c1be1",
    ),
    "hero_modal": (
        ROOT / "fixtures" / "live_postgame_20260808" / "live_archive_start_panel.png",
        "e52490192f63c641166e8b99e3f2b124160d6c8873a12a2daa3ccc6e0269929e",
    ),
}

CROPS = (
    ("exit", (708, 516, 781, 546), "exit_confirm_btn.png"),
    ("exit", (819, 516, 893, 546), "exit_cancel_btn.png"),
    ("archive", (974, 224, 1017, 255), "archive_panel_close.png"),
    # The source fixture name predates its classification.  It is the real
    # hero-mode modal from the user's 1600x900 recording, not an archive UI.
    ("stage", (1190, 807, 1254, 838), "stage_hero_mode_btn.png"),
    ("hero_modal", (557, 833, 712, 887), "hero_modal_start.png"),
    ("hero_modal", (770, 833, 924, 887), "hero_modal_cancel.png"),
    ("hero_modal", (662, 118, 815, 286), "hero_kenrito_unselected.png"),
    ("hero_modal", (724, 314, 752, 342), "hero_level_zero.png"),
)


def main() -> None:
    output_dir = ROOT / "assets" / "Images" / "lobby"
    for source_key, (source, expected_sha256) in SOURCES.items():
        actual_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise RuntimeError(f"source changed: {source}")

    for source_key, box, filename in CROPS:
        source = SOURCES[source_key][0]
        with Image.open(source) as image:
            image.crop(box).save(output_dir / filename)
        print(f"wrote {output_dir / filename} from {source.name} {box}")


if __name__ == "__main__":
    main()
