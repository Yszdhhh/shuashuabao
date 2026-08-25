#!/usr/bin/env python3
"""玩家画像采集入口：截图 → OCR → 落盘。零点击、零按键。

真机：先自己停在「存档 → 技能」总览；或一进图按 TAB 打开属性面板再跑。
TAB 是装备堆叠后的进图默认盘，打一半再采不当画像。
TAB 纯查看无副作用，但本入口不代按，避免 UNKNOWN 屏乱输入。

真机必须占 ShuaBao.live.lock（与 08/09/10/看板 LIVE 互斥）。
--from-file 离线扫夹具，不占车道。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.player_profile import (  # noqa: E402
    TAB_WINDOW_ENTRY,
    LiveLane,
    LiveLaneBusy,
    build_poster,
    classify_tab_window,
    default_profile_dir,
    detect_scan_kind,
    parse_attr_panel,
    parse_equipment,
    parse_skill_levels,
    upsert_first_login,
    write_profile,
)
from gamescript.vision.capture import (  # noqa: E402
    L1_WINDOW_KEYWORDS,
    Frame,
    capture_target,
    find_window_targets,
)

_REGIONS = (
    (0.00, 0.00, 1.00, 1.00),
    (0.08, 0.10, 0.92, 0.90),
    (0.05, 0.12, 0.48, 0.92),
)


def _load_bgr(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"读不了图: {path}")
    return image


def _save_png(bgr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError(f"写不了图: {path}")
    encoded.tofile(str(path))


def _capture_l1() -> Frame:
    query = ",".join(L1_WINDOW_KEYWORDS)
    targets = find_window_targets(query, role="l1")
    if not targets:
        raise RuntimeError("找不到 L1 游戏窗。先开游戏，停在存档技能页或 TAB 属性面板。")
    frame = capture_target(targets[0], activate=False)
    if not frame.is_valid or frame.width < 200 or frame.height < 200:
        raise RuntimeError(f"截图失败: {frame.error or f'{frame.width}x{frame.height}'}")
    return frame


def _ocr_frame(frame: Frame) -> tuple[str, float]:
    from gamescript.vision.ocr_shadow.client import ShadowClient

    client = ShadowClient(repo_root=ROOT, timeout_ms=4000, startup_timeout_ms=12000)
    try:
        if not client.ping(timeout_ms=12000):
            raise RuntimeError("OCR sidecar 不可用，未落盘（fail-closed）。")
        chunks: list[str] = []
        scores: list[float] = []
        h, w = frame.height, frame.width
        for idx, (x0, y0, x1, y1) in enumerate(_REGIONS):
            bbox = (int(w * x0), int(h * y0), int(w * x1), int(h * y1))
            if bbox[2] - bbox[0] < 16 or bbox[3] - bbox[1] < 16:
                continue
            slot = {"slot_id": idx, "bbox": bbox, "kind": "treasure"}
            resp = client.shadow_predict(frame, f"profile_{idx}", slot)
            if not resp.available:
                continue
            text = (resp.raw_text or "").strip()
            if not text and resp.candidates:
                text = str(resp.candidates[0].name or "").strip()
            if text:
                chunks.append(text)
            if resp.rec_score is not None:
                scores.append(float(resp.rec_score))
            elif resp.candidates:
                scores.append(float(resp.candidates[0].confidence))
        if not chunks:
            raise RuntimeError("OCR 无字，未落盘（fail-closed）。")
        conf = min(scores) if scores else 0.0
        return "\n".join(chunks), conf
    finally:
        client.close()


def _print_skills(parsed: dict) -> None:
    print("skill_id  name    level  conf   status")
    for skill_id, row in parsed.items():
        level = row.get("level")
        level_s = "-" if level is None else str(level)
        print(
            f"{skill_id:<8} {row.get('name', ''):<6} {level_s:<5} "
            f"{row.get('conf', 0):<6} {row.get('status')}"
        )


def _print_attrs(parsed: dict) -> None:
    print("id              name      value  conf   status")
    for field_id, row in parsed.items():
        value = row.get("value")
        value_s = "-" if value is None else str(value)
        print(
            f"{field_id:<15} {row.get('name', ''):<8} {value_s:<6} "
            f"{row.get('conf', 0):<6} {row.get('status')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-file", default="", help="离线扫一张静帧，不占真机车道")
    parser.add_argument("--kind", choices=("auto", "skills", "attrs", "equipment"), default="auto")
    parser.add_argument("--out-dir", default="", help="默认 %%LocalAppData%%/ShuaBao/profiles/")
    parser.add_argument("--no-save-frame", action="store_true")
    parser.add_argument(
        "--bind",
        action="store_true",
        help="勾选画像绑定才写入 first_login_*.json；不点存档，人先打开装备/技能页",
    )
    args = parser.parse_args()

    dest = Path(args.out_dir) if args.out_dir else default_profile_dir()
    live = None
    try:
        if args.from_file:
            path = Path(args.from_file)
            bgr = _load_bgr(path)
            frame = Frame(bgr=bgr, window_title=path.name)
            print(f"from-file {path} {frame.width}x{frame.height}")
        else:
            print("零点击。绑定：人先点顶栏「存档」，停在装备或技能页。")
            print("TAB：一进图按开属性面板立刻采。打一半的盘不当默认。不要和 08/09/10/看板 LIVE 同时开。")
            live = LiveLane("profile_scan")
            live.acquire()
            frame = _capture_l1()
            print(f"hwnd={frame.hwnd} title={frame.window_title!r} {frame.width}x{frame.height}")

        text, conf = _ocr_frame(frame)
        kind = args.kind
        if kind == "auto":
            kind = detect_scan_kind(text)
        if kind is None:
            print("未识别到存档装备/技能页或 TAB 属性面板，零输入退出。")
            print(f"ocr_preview={text[:200]!r}")
            return 2

        frame_path = ""
        if not args.no_save_frame:
            stem = {"skills": "skill_levels", "attrs": "tab_attrs", "equipment": "equipment"}[kind]
            frame_path = str(dest / f"{stem}_{frame.width}x{frame.height}.png")
            _save_png(frame.bgr, Path(frame_path))

        meta = {"resolution": f"{frame.width}x{frame.height}", "ocr_conf": conf}
        if kind == "skills":
            parsed = parse_skill_levels(text, conf=conf)
            out = write_profile("skills", {**meta, "skills": parsed}, dest_dir=dest, frame_path=frame_path)
            _print_skills(parsed)
            if args.bind:
                out = upsert_first_login(dest_dir=dest, skills=parsed, opt_in=True, frame_path=frame_path)
        elif kind == "equipment":
            parsed = parse_equipment(text, conf=conf)
            out = write_profile("equipment", {**meta, "equipment": parsed}, dest_dir=dest, frame_path=frame_path)
            print(parsed)
            if args.bind:
                out = upsert_first_login(dest_dir=dest, equipment=parsed, opt_in=True, frame_path=frame_path)
        else:
            parsed = parse_attr_panel(text, conf=conf)
            window = classify_tab_window(text)
            print(f"tab_window={window}")
            if window != TAB_WINDOW_ENTRY:
                print("不是进图默认盘，海报七格保持未采集。一进图按 TAB 再采。")
            out = write_profile(
                "attrs",
                {**meta, "tab_window": window, "attrs": parsed},
                dest_dir=dest,
                frame_path=frame_path,
            )
            _print_attrs(parsed)
            if args.bind:
                bind_path = dest / f"first_login_{datetime.now().strftime('%Y%m%d')}.json"
                bind = {}
                if bind_path.is_file():
                    try:
                        loaded = json.loads(bind_path.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            bind = loaded
                    except (OSError, ValueError, TypeError):
                        bind = {}
                out = write_profile(
                    "poster",
                    build_poster(bind=bind, tab_attrs=parsed, tab_window=window),
                    dest_dir=dest,
                    frame_path=frame_path,
                )
        print(f"wrote {out}")
        print("未写入 Settings / 仓库 config。conf 低的是 unverified。")
        return 0
    except LiveLaneBusy as exc:
        print(f"车道占用: {exc}")
        return 3
    except RuntimeError as exc:
        print(f"fail-closed: {exc}")
        return 2
    finally:
        if live is not None:
            live.release()


if __name__ == "__main__":
    raise SystemExit(main())
