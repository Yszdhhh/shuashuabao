#!/usr/bin/env python3
"""Validate scenes.json templates + card template bidirectional assertions.

Card bidirectional rules (fixtures/card_template_assertions/, EVOLVE lesson):
  * inventory: every shortcode PNG exists; fetter_labels sync
  * positive: template self-match ≥ positive_min; known panel hits stay ≥ positive_min
  * blank negative (black_frame): score ≤ negative_max
  * unrelated negative (idle_hud): score must stay < positive_min
    (must not false-fire at the operating click threshold; idle HUD shares
    cyan outlined UI text so ≤0.4 is not always achievable for tiny name crops)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "assets" / "Images"
SCENES = ROOT / "config" / "scenes.json"
FETTER_LABELS = ROOT / "config" / "fetter_labels.json"
CARD_ASSERT_INDEX = ROOT / "fixtures" / "card_template_assertions" / "templates_index.json"

# Panel hits locked from the packed fixtures (zhufu is the only ≥0.9 panel hit).
REQUIRED_PANEL_HITS: dict[str, tuple[str, ...]] = {
    "zhufu": (
        "fixtures/card_template_assertions/positives/bond_choice_3.png",
        "fixtures/card_template_assertions/positives/bond_panel.png",
    ),
}


def imread_unicode(path: Path):
    """读图；必须走 imdecode 而不是 cv2.imread。

    仓库实际所在目录含非 ASCII 字符（`🎮 影音游戏`），Windows 上 cv2.imread
    对这类路径会静默返回 None。生产侧 `vision/matcher.py` 早就为此改用
    np.fromfile + imdecode，工具与测试必须保持一致，否则在云端（ASCII 路径）
    全绿、到用户机器上全红。
    """
    import cv2
    import numpy as np

    if not path.is_file():
        return None
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def resolve(name: str) -> Path | None:
    n = name if name.lower().endswith(".png") else f"{name}.png"
    for c in [
        IMAGES / n,
        IMAGES / Path(n).name,
        IMAGES / "skills" / Path(n).name,
        IMAGES / "cards" / Path(n).name,
        IMAGES / "boss" / Path(n).name,
        IMAGES / "chuanjiaobao" / Path(n).name,
    ]:
        if c.is_file():
            return c
    stem = Path(n).stem
    for f in IMAGES.rglob("*.png"):
        if f.stem == stem:
            return f
    return None


def _match_score(image, template) -> float:
    import cv2

    if image is None or template is None:
        return -1.0
    if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
        return -1.0
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(result)[1])


def _is_blank_negative(path: Path) -> bool:
    stem = path.stem.lower()
    return "black" in stem or "blank" in stem or "empty" in stem


def validate_card_bidirectional() -> tuple[int, int, list[str]]:
    """Run card template bidirectional assertions. Returns (ok, fail, errors)."""
    import cv2

    if not CARD_ASSERT_INDEX.is_file():
        return 0, 1, [f"missing assertion index: {CARD_ASSERT_INDEX.relative_to(ROOT)}"]

    index = json.loads(CARD_ASSERT_INDEX.read_text(encoding="utf-8"))
    thresholds = index.get("thresholds") or {}
    positive_min = float(thresholds.get("positive_min", 0.9))
    negative_max = float(thresholds.get("negative_max", 0.4))
    shortcodes = list(index.get("shortcodes") or [])
    templates_dir = ROOT / str(index.get("templates_dir") or "assets/Images/cards")

    labels_doc = json.loads(FETTER_LABELS.read_text(encoding="utf-8"))
    label_keys = {k for k in labels_doc if not str(k).startswith("_")}

    errors: list[str] = []
    ok = 0

    # --- inventory ---
    missing_files = [c for c in shortcodes if not (templates_dir / f"{c}.png").is_file()]
    disk_stems = {p.stem for p in templates_dir.glob("*.png")}
    label_missing = sorted(set(shortcodes) - label_keys)
    template_missing = sorted(label_keys - set(shortcodes))
    if missing_files:
        errors.append(f"card templates missing on disk: {missing_files}")
    if label_missing:
        errors.append(f"fetter_labels missing shortcodes: {label_missing}")
    if template_missing:
        errors.append(f"card PNG missing for fetter_labels: {template_missing}")
    if index.get("label_missing_for_template") not in (None, [], label_missing):
        # index claims empty gaps; enforce reality matches claim when claim is empty
        claimed = index.get("label_missing_for_template") or []
        if claimed != label_missing and not claimed and label_missing:
            errors.append("templates_index.label_missing_for_template stale vs fetter_labels")
    if len(shortcodes) != int(index.get("count") or len(shortcodes)):
        errors.append(
            f"templates_index.count={index.get('count')} != len(shortcodes)={len(shortcodes)}"
        )
    if disk_stems != set(shortcodes):
        extra = sorted(disk_stems - set(shortcodes))
        missing = sorted(set(shortcodes) - disk_stems)
        if extra:
            errors.append(f"cards/ has PNGs not in templates_index: {extra}")
        if missing:
            errors.append(f"templates_index shortcodes missing PNG: {missing}")

    # --- load frames ---
    positive_frames: list[tuple[str, object]] = []
    for rel in index.get("positive_frames") or []:
        path = ROOT / rel
        img = imread_unicode(path) if path.is_file() else None
        if img is None:
            errors.append(f"positive frame unreadable: {rel}")
        else:
            positive_frames.append((rel, img))

    blank_frames: list[tuple[str, object]] = []
    unrelated_frames: list[tuple[str, object]] = []
    for rel in index.get("negative_frames") or []:
        path = ROOT / rel
        img = imread_unicode(path) if path.is_file() else None
        if img is None:
            errors.append(f"negative frame unreadable: {rel}")
            continue
        if _is_blank_negative(path):
            blank_frames.append((rel, img))
        else:
            unrelated_frames.append((rel, img))

    if not blank_frames:
        errors.append("no blank negative frames (need black_frame) for ≤ negative_max check")

    # --- per-template bidirectional ---
    panel_hit_codes: list[str] = []
    warn_unrelated: list[str] = []

    for code in shortcodes:
        tpl_path = templates_dir / f"{code}.png"
        if not tpl_path.is_file():
            continue
        template = imread_unicode(tpl_path)
        if template is None:
            errors.append(f"{code}: unreadable PNG")
            continue

        # Positive (source crop identity)
        self_score = _match_score(template, template)
        if self_score < positive_min:
            errors.append(f"{code}: self positive {self_score:.4f} < {positive_min}")
        else:
            ok += 1

        # Blank negatives must stay ≤ negative_max
        for rel, img in blank_frames:
            score = _match_score(img, template)
            if score < 0:
                errors.append(f"{code}: blank frame too small for template ({rel})")
            elif score > negative_max:
                errors.append(
                    f"{code}: blank negative {score:.4f} > {negative_max} on {rel}"
                )
            else:
                ok += 1

        # Unrelated: must not reach click threshold (false-fire guard)
        for rel, img in unrelated_frames:
            score = _match_score(img, template)
            if score < 0:
                errors.append(f"{code}: unrelated frame too small for template ({rel})")
            elif score >= positive_min:
                errors.append(
                    f"{code}: unrelated false-fire {score:.4f} ≥ {positive_min} on {rel}"
                )
            else:
                ok += 1
                if score > negative_max:
                    warn_unrelated.append(f"{code}:{score:.3f}@{Path(rel).name}")

        # Panel positive scan
        best_panel = -1.0
        for rel, img in positive_frames:
            score = _match_score(img, template)
            if score > best_panel:
                best_panel = score
        if best_panel >= positive_min:
            panel_hit_codes.append(code)
            ok += 1

    # Required panel hits (regression lock for evidenced templates)
    for code, frames in REQUIRED_PANEL_HITS.items():
        tpl_path = templates_dir / f"{code}.png"
        template = imread_unicode(tpl_path) if tpl_path.is_file() else None
        if template is None:
            errors.append(f"required panel hit {code}: template missing")
            continue
        for rel in frames:
            img = imread_unicode(ROOT / rel)
            score = _match_score(img, template)
            if score < positive_min:
                errors.append(
                    f"required panel hit {code} on {rel}: {score:.4f} < {positive_min}"
                )
            else:
                ok += 1

    if not panel_hit_codes:
        errors.append(
            "no card template scored ≥ positive_min on packed positive panels "
            "(expected at least zhufu)"
        )

    fail = len(errors)
    print(
        f"card_bidir ok={ok} fail={fail} panel_hits={len(panel_hit_codes)} "
        f"positive_min={positive_min} negative_max={negative_max}"
    )
    if panel_hit_codes:
        print(f" card_bidir_panel_hits {','.join(panel_hit_codes)}")
    if warn_unrelated:
        print(
            f" card_bidir_warn unrelated>{negative_max} "
            f"count={len(warn_unrelated)} (below click thr {positive_min})"
        )
        for w in warn_unrelated[:20]:
            print(f"  WARN {w}")
    for err in errors:
        print(f" CARD_BIDIR_FAIL {err}")
    return ok, fail, errors


def main() -> int:
    doc = json.loads(SCENES.read_text(encoding="utf-8"))
    missing: list[str] = []
    ok = 0
    for key, sc in doc.get("scenes", {}).items():
        for t in sc.get("templates") or []:
            if resolve(t):
                ok += 1
            else:
                missing.append(f"{key}: {t}")
    print(f"ok={ok} missing={len(missing)}")
    for m in missing:
        print(" MISSING", m)
    # list root pngs not referenced
    referenced = set()
    for sc in doc.get("scenes", {}).values():
        for t in sc.get("templates") or []:
            referenced.add(Path(t).stem)
    for name in doc.get("combat_templates_root_unclassified") or []:
        referenced.add(name)
    unref = []
    for f in IMAGES.glob("*.png"):
        if f.stem not in referenced:
            unref.append(f.name)
    print(f"root_unreferenced={len(unref)}")
    for u in sorted(unref)[:40]:
        print(" UNREF", u)

    _bidir_ok, bidir_fail, _ = validate_card_bidirectional()
    if missing or bidir_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
