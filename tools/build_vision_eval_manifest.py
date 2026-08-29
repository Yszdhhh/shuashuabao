#!/usr/bin/env python3
"""Build a provenance-first JSONL manifest for the vision/OCR corpus.

The input file is intentionally treated as annotation metadata only.  Every
source image is opened from ``corpus_root`` and its byte hash, dimensions,
dHash and pHash are recomputed.  Duplicate cluster identifiers are generated
from those image hashes; they never contain a label or a scene name.

The generator keeps capture sessions intact.  It fails closed if a capture
session or a perceptual cluster crosses the requested split boundary instead
of silently producing a leakage-prone train/holdout split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "docs" / "distillation" / "VISION_EVAL_ANNOTATIONS.jsonl"
DEFAULT_CORPUS_ROOT = REPO_ROOT / "fixtures" / "ocr_choices"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "distillation" / "VISION_EVAL_MANIFEST.jsonl"
DEFAULT_ANNOTATIONS_OUTPUT = REPO_ROOT / "docs" / "distillation" / "VISION_EVAL_ANNOTATIONS.jsonl"

# Conservative thresholds for small title crops.  Both hashes must be close,
# which avoids merging merely similar Chinese glyphs on one hash alone.
DHASH_MAX_HAMMING = 8
PHASH_MAX_HAMMING = 16


class ManifestError(ValueError):
    """Raised when the corpus cannot be represented without leakage."""


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _read_rows(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(item, dict):
            raise ManifestError(f"{path}:{line_no}: record must be an object")
        if "_manifest" in item:
            if meta:
                raise ManifestError(f"{path}:{line_no}: duplicate _manifest header")
            meta = dict(item["_manifest"] or {})
        else:
            rows.append(item)
    if not rows:
        raise ManifestError(f"{path}: no sample records")
    return meta, rows


def _resolve_crop(corpus_root: Path, source_crop: Any) -> tuple[Path, str]:
    if not isinstance(source_crop, str) or not source_crop.strip():
        raise ManifestError("source_crop must be a non-empty relative path")
    rel = Path(source_crop.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise ManifestError(f"source_crop must stay below corpus_root: {source_crop!r}")
    resolved_root = corpus_root.resolve()
    full = (resolved_root / rel).resolve()
    try:
        full.relative_to(resolved_root)
    except ValueError as exc:
        raise ManifestError(f"source_crop escapes corpus_root: {source_crop!r}") from exc
    if not full.is_file():
        raise ManifestError(f"source_crop does not exist: {full}")
    return full, rel.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pack_bits(bits: np.ndarray) -> str:
    value = 0
    for bit in bits.astype(bool).flat:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def _image_hashes(path: Path) -> dict[str, Any]:
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if image is None or image.size == 0:
        raise ManifestError(f"cannot decode source crop: {path}")

    # 64-bit dHash: horizontal gradients over an 8x9 thumbnail.
    dhash_image = cv2.resize(image, (9, 8), interpolation=cv2.INTER_AREA)
    dhash = _pack_bits(dhash_image[:, 1:] >= dhash_image[:, :-1])

    # 64-bit pHash: low-frequency 8x8 DCT, excluding the DC coefficient from
    # the median threshold as is customary for perceptual image hashing.
    phash_image = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(phash_image.astype(np.float32))[:8, :8]
    phash = _pack_bits(dct >= float(np.median(dct[1:, :])))

    return {
        "sha256": _sha256(path),
        "image_size": [int(image.shape[1]), int(image.shape[0])],
        "dhash": dhash,
        "phash": phash,
        "image_bytes": int(path.stat().st_size),
    }


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def _cluster(records: list[dict[str, Any]]) -> dict[int, list[int]]:
    dsu = _DisjointSet(len(records))
    for index, left in enumerate(records):
        for other, right in enumerate(records[:index]):
            exact = left["sha256"] == right["sha256"]
            near = (
                _hamming(left["dhash"], right["dhash"]) <= DHASH_MAX_HAMMING
                and _hamming(left["phash"], right["phash"]) <= PHASH_MAX_HAMMING
            )
            if exact or near:
                dsu.union(index, other)
    clusters: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        clusters[dsu.find(index)].append(index)
    return dict(clusters)


def _validate_boundaries(rows: list[dict[str, Any]], cluster_ids: list[str]) -> None:
    session_splits: dict[str, set[str]] = defaultdict(set)
    cluster_splits: dict[str, set[str]] = defaultdict(set)
    for row, cluster_id in zip(rows, cluster_ids):
        session = str(row.get("capture_session") or "").strip()
        split = str(row.get("split") or "").strip()
        if not session:
            raise ManifestError(f"{row.get('sample_id')!r}: missing capture_session")
        if split not in {"TRAIN_TUNE", "BLIND_HOLDOUT"}:
            raise ManifestError(f"{row.get('sample_id')!r}: unsupported split {split!r}")
        session_splits[session].add(split)
        cluster_splits[cluster_id].add(split)
    bad_sessions = {key: sorted(value) for key, value in session_splits.items() if len(value) > 1}
    bad_clusters = {key: sorted(value) for key, value in cluster_splits.items() if len(value) > 1}
    if bad_sessions:
        raise ManifestError(f"capture session crosses split boundary: {bad_sessions}")
    if bad_clusters:
        raise ManifestError(f"near-duplicate cluster crosses split boundary: {bad_clusters}")


def build_manifest(
    input_path: Path,
    corpus_root: Path,
    *,
    generated_at: str | None = None,
    source_manifest_path: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _, source_rows = _read_rows(input_path)
    if len({str(row.get("sample_id")) for row in source_rows}) != len(source_rows):
        raise ManifestError("sample_id values must be unique")

    enriched: list[dict[str, Any]] = []
    for source in source_rows:
        full, relative = _resolve_crop(corpus_root, source.get("source_crop"))
        facts = _image_hashes(full)
        row = dict(source)
        row.update(facts)
        row["source_crop"] = relative
        row["corpus_root"] = _repo_relative(corpus_root)
        row["capture_group_id"] = f"capture_session:{str(row.get('capture_session') or '').strip()}"
        row["source_split"] = str(source.get("split") or "").strip()
        enriched.append(row)

    clusters = _cluster(enriched)
    ordered_clusters = sorted(
        clusters.values(),
        key=lambda members: min(
            (str(enriched[index].get("source_crop")), str(enriched[index].get("sample_id")))
            for index in members
        ),
    )
    cluster_by_index: dict[int, tuple[str, str, int]] = {}
    for serial, members in enumerate(ordered_clusters, 1):
        cluster_id = f"phash_dhash_cluster_{serial:04d}"
        exact = len({enriched[index]["sha256"] for index in members}) == 1
        kind = "exact_duplicate" if exact and len(members) > 1 else (
            "near_duplicate" if len(members) > 1 else "unique"
        )
        for index in members:
            cluster_by_index[index] = (cluster_id, kind, len(members))

    cluster_ids = [cluster_by_index[index][0] for index in range(len(enriched))]
    _validate_boundaries(enriched, cluster_ids)
    for index, row in enumerate(enriched):
        cluster_id, kind, size = cluster_by_index[index]
        row["duplicate_cluster_id"] = cluster_id
        row["duplicate_cluster_kind"] = kind
        row["duplicate_cluster_size"] = size
        row["near_duplicate"] = kind == "near_duplicate"
        row["exact_duplicate"] = kind == "exact_duplicate"

    sessions = Counter(str(row["capture_session"]) for row in enriched)
    split_counts = Counter(str(row["split"]) for row in enriched)
    multi_clusters = [members for members in clusters.values() if len(members) > 1]
    exact_clusters = [
        members
        for members in multi_clusters
        if len({enriched[index]["sha256"] for index in members}) == 1
    ]
    meta = {
        "schema_version": 3,
        "format": "jsonl",
        "corpus_root": _repo_relative(corpus_root),
        "source_manifest": _repo_relative(source_manifest_path or input_path),
        "source_crop_policy": "source_crop is relative to corpus_root and is hash-verified",
        "capture_session_field": "capture_session",
        "split_policy": "whole capture_session; reject any cluster crossing split",
        "duplicate_algorithm": {
            "name": "sha256 OR (dHash + pHash) union-find",
            "dhash": "8x9 grayscale horizontal gradient, 64-bit",
            "phash": "32x32 grayscale DCT low-frequency 8x8, 64-bit",
            "dhash_max_hamming": DHASH_MAX_HAMMING,
            "phash_max_hamming": PHASH_MAX_HAMMING,
            "cluster_id_prefix": "phash_dhash_cluster_",
        },
        "generated_at_utc": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {
            "samples": len(enriched),
            "sessions": len(sessions),
            "train_tune": split_counts["TRAIN_TUNE"],
            "blind_holdout": split_counts["BLIND_HOLDOUT"],
            "exact_duplicate_clusters": len(exact_clusters),
            "exact_duplicate_samples": sum(len(group) for group in exact_clusters),
            "near_duplicate_clusters": len(multi_clusters) - len(exact_clusters),
            "near_duplicate_samples": sum(
                len(group) for group in multi_clusters if group not in exact_clusters
            ),
            "unique_clusters": len(clusters),
        },
        "session_counts": dict(sorted(sessions.items())),
    }
    return meta, enriched


def write_manifest(path: Path, meta: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"_manifest": meta}, ensure_ascii=False, sort_keys=True)]
    lines.extend(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_annotation_source(path: Path, rows: list[dict[str, Any]], corpus_root: Path) -> None:
    """Persist only the human/source annotation fields before regeneration.

    This is useful when the supplied Stage 1 file is itself the requested
    output path: the regenerated manifest then points to an immutable-looking
    annotation export rather than claiming that it was its own source.
    """
    fields = (
        "sample_id", "capture_session", "scene", "label", "truth_status",
        "split", "risk_class", "roi", "source_crop",
    )
    meta = {
        "schema_version": 1,
        "format": "jsonl",
        "purpose": "Stage 1 annotation export preserved before provenance regeneration",
        "corpus_root": _repo_relative(corpus_root),
        "source_crop_policy": "source_crop is relative to corpus_root",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"_manifest": meta}, ensure_ascii=False, sort_keys=True)]
    for row in rows:
        lines.append(json.dumps({key: row.get(key) for key in fields}, ensure_ascii=False, sort_keys=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--annotations-output",
        type=Path,
        default=DEFAULT_ANNOTATIONS_OUTPUT,
        help="when input and output are the same, preserve raw annotation fields here first",
    )
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument(
        "--generated-at",
        help="fixed timestamp for byte-reproducible output; defaults to current UTC",
    )
    args = parser.parse_args(argv)
    input_path = args.input if args.input.is_absolute() else REPO_ROOT / args.input
    output_path = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    annotations_path = (
        args.annotations_output
        if args.annotations_output.is_absolute()
        else REPO_ROOT / args.annotations_output
    )
    corpus_root = args.corpus_root if args.corpus_root.is_absolute() else REPO_ROOT / args.corpus_root
    source_manifest_path = input_path
    if input_path.resolve() == output_path.resolve():
        _, source_rows = _read_rows(input_path)
        write_annotation_source(annotations_path, source_rows, corpus_root)
        source_manifest_path = annotations_path
    meta, rows = build_manifest(
        input_path,
        corpus_root,
        generated_at=args.generated_at,
        source_manifest_path=source_manifest_path,
    )
    write_manifest(output_path, meta, rows)
    print(json.dumps(meta["counts"], ensure_ascii=False, sort_keys=True))
    print(f"[manifest] output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
