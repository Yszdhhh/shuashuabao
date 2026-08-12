#!/usr/bin/env python3
"""GameScript-Local CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from gamescript.incidents import default_incident_dir
from gamescript.jobs import AutoJob, LongzhuJob
from gamescript.mediator import Mediator
from gamescript.models.skill import get_all_card_groups, get_all_skills, get_boss_list
from gamescript.settings import Settings
from gamescript.vision.capture import capture
from gamescript.vision.matcher import match_one, resolve_template


def load_settings(path: Path | None) -> Settings:
    if path:
        return Settings.load(path)
    # 优先官方配置（含最新 Skills），否则本地 default
    try:
        s = Settings.load_official()
        s.dry_run = True
        s.game_mode = 0
        if not s.window_title_contains:
            s.window_title_contains = "英雄三国"
        return s
    except FileNotFoundError:
        return Settings.load(ROOT / "config" / "default_settings.json")


def cmd_match(args: argparse.Namespace) -> int:
    s = load_settings(Path(args.config) if args.config else None)
    if args.title:
        s.window_title_contains = args.title
    images = s.images_path(ROOT)
    path = resolve_template(images, args.template)
    if not path:
        print(f"template not found: {args.template} under {images}")
        return 1
    frame = capture(s.window_title_contains or "")
    hit = match_one(frame, path, threshold=s.match_threshold, name=path.stem)
    if not hit:
        print(f"NO MATCH {path.name} threshold={s.match_threshold} frame={frame.width}x{frame.height}")
        return 2
    print(f"OK {hit.name} score={hit.score:.4f} center=({hit.screen_x},{hit.screen_y})")
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    s = load_settings(Path(args.config) if args.config else None)
    s.dry_run = True
    if args.legacy:
        job = LongzhuJob(s, ROOT) if args.longzhu else AutoJob(s, ROOT)
        job.run(max_steps=args.steps)
    else:
        # S0.5：CLI 生产入口也传入 incident 目录（默认 %LocalAppData%/ShuaBao/incidents）
        med = Mediator(s, ROOT, incident_dir=default_incident_dir())
        med.set_trace(str(ROOT / "logs" / f"trace_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"))
        med.run(max_steps=args.steps)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    s = load_settings(Path(args.config) if args.config else None)
    s.dry_run = False
    if args.legacy:
        print("[SECURITY ERROR] --legacy mode does not support real input (dry_run=False) because it bypasses P0 security chain. Use Mediator runner instead.")
        return 1
    print("WARNING: will move mouse / click. Ctrl+C to stop.")
    try:
        # S0.5：CLI 生产入口也传入 incident 目录（默认 %LocalAppData%/ShuaBao/incidents）
        med = Mediator(s, ROOT, incident_dir=default_incident_dir())
        med.set_trace(str(ROOT / "logs" / f"trace_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"))
        med.run(max_steps=args.steps)
    except KeyboardInterrupt:
        print("stopped by user")
    return 0


def cmd_inventory(_: argparse.Namespace) -> int:
    s = load_settings(None)
    images = s.images_path(ROOT)
    print("skills", len(get_all_skills(images)))
    print("cards", len(get_all_card_groups(images)))
    print("boss", len(get_boss_list(images, "boss")))
    print("chuanjiaobao", len(get_boss_list(images, "chuanjiaobao")))
    root_png = list(images.glob("*.png"))
    print("root_templates", len(root_png))
    return 0


def cmd_sync_settings(args: argparse.Namespace) -> int:
    """从官方 Settings.json 同步到本地 config。"""
    s = Settings.load_official()
    s.game_mode = 0
    s.dry_run = True
    if not s.window_title_contains:
        s.window_title_contains = "英雄三国"
    out = Path(args.out) if args.out else ROOT / "config" / "default_settings.json"
    s.save(out)
    print("synced →", out)
    print("skills =", s.skills)
    print("stage  =", s.stage1, s.stage2)
    print("boss   =", s.cjb_boss, s.sgzx_boss)
    missing = []
    img = s.images_path(ROOT)
    for code in s.skills:
        if not (img / "skills" / f"{code}.png").is_file():
            missing.append(code)
    print("skill templates missing:", missing or "none")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="GameScript-Local")
    p.add_argument("--config", default=None, help="settings json path")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("match", help="match one template on screen")
    m.add_argument("--template", required=True)
    m.add_argument("--title", default="", help="window title contains")
    m.set_defaults(func=cmd_match)

    d = sub.add_parser("dry-run", help="mediator loop without clicking")
    d.add_argument("--steps", type=int, default=20)
    d.add_argument("--longzhu", action="store_true", help="legacy LongzhuJob only")
    d.add_argument("--legacy", action="store_true", help="use old AutoJob instead of Mediator")
    d.set_defaults(func=cmd_dry_run)

    r = sub.add_parser("run", help="mediator loop with real clicks")
    r.add_argument("--steps", type=int, default=None)
    r.add_argument("--longzhu", action="store_true", help="legacy LongzhuJob only")
    r.add_argument("--legacy", action="store_true", help="use old AutoJob instead of Mediator")
    r.set_defaults(func=cmd_run)

    inv = sub.add_parser("inventory", help="count templates")
    inv.set_defaults(func=cmd_inventory)

    sy = sub.add_parser("sync-settings", help="import official AppData Settings.json")
    sy.add_argument("--out", default=None, help="write path (default config/default_settings.json)")
    sy.set_defaults(func=cmd_sync_settings)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
