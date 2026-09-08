#!/usr/bin/env python3
"""Generate the explicit allowlist consumed by the release asset gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "config" / "runtime_asset_manifest.json"
FORBIDDEN_PATH_TOKENS = [
    "capture",
    "corpus",
    "debug",
    "evidence",
    "failure",
    "fixture",
    "incident",
    "recording",
    "scratch",
    "training",
    "trace",
    "video_frames",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _purpose(path: Path) -> tuple[str, str]:
    parts = {part.lower() for part in path.relative_to(ROOT / "assets").parts}
    if "branding" in parts:
        return "branding", "packaged application branding"
    if parts & {"cards", "skills", "boss", "chuanjiaobao"}:
        return "runtime_template", "runtime visual matching template"
    return "runtime_ui", "runtime UI/status/icon asset"


def generate(output: Path, generated_at: str | None = None) -> dict:
    asset_root = ROOT / "assets"
    paths = sorted(path for path in asset_root.rglob("*") if path.is_file())
    entries = []
    for path in paths:
        purpose, reason = _purpose(path)
        rel = path.relative_to(ROOT).as_posix()
        entries.append(
            {
                "path": rel,
                "purpose": purpose,
                "provenance": "repository runtime asset reviewed for ShuaBao.spec",
                "reason_required": reason,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    report = {
        "schema_version": 1,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "spec": "ShuaBao.spec",
        "package_roots": [
            {
                "source": "assets",
                "target": "assets",
                "mode": "whole_tree",
                "policy": "every file must be explicitly allowlisted and hash-verified",
            }
        ],
        "forbidden_path_tokens": FORBIDDEN_PATH_TOKENS,
        "entries": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at")
    args = parser.parse_args(argv)
    report = generate(args.json_out, args.generated_at)
    print(json.dumps({"status": "COMPLETED", "json": str(args.json_out.resolve()), "entries": len(report["entries"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
