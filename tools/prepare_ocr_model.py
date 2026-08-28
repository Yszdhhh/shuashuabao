#!/usr/bin/env python3
"""Prepare the pinned OCR model archive for a reproducible release build."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from typing import Any
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "models" / "ocr" / "MODEL_MANIFEST.json"
MODEL_NAME = "PP-OCRv5_mobile_rec_infer"
MODEL_FILES = ("inference.json", "inference.pdiparams", "inference.yml")


class ModelPreparationError(RuntimeError):
    """A model cannot be proven safe to package."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_entry(manifest_path: Path, model_name: str) -> dict[str, Any]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelPreparationError(f"cannot read OCR manifest: {manifest_path}") from exc
    if data.get("schema_version") != 2 or not isinstance(data.get("models"), list):
        raise ModelPreparationError("OCR manifest must use schema_version 2 with a models list")
    for entry in data["models"]:
        if entry.get("name") == model_name:
            return entry
    raise ModelPreparationError(f"OCR manifest has no model entry for {model_name!r}")


def _verify_files(model_dir: Path, entry: dict[str, Any]) -> None:
    files = entry.get("files") or {}
    if not files:
        raise ModelPreparationError("OCR model entry has no file hashes")
    for name in MODEL_FILES:
        expected = files.get(name)
        path = model_dir / name
        if not isinstance(expected, dict) or not path.is_file():
            raise ModelPreparationError(f"OCR model file missing: {path}")
        try:
            size = path.stat().st_size
            digest = sha256_file(path)
            expected_size = int(expected["size_bytes"])
            expected_hash = str(expected["sha256"]).upper()
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ModelPreparationError(f"cannot verify OCR model file: {path}") from exc
        if size != expected_size or digest != expected_hash:
            raise ModelPreparationError(
                f"OCR model hash mismatch: {path} "
                f"(size {size}/{expected_size}, sha256 {digest}/{expected_hash})"
            )


def _verify_archive(archive_path: Path, entry: dict[str, Any]) -> None:
    spec = entry.get("archive") or {}
    if not archive_path.is_file():
        raise ModelPreparationError(f"OCR model archive missing: {archive_path}")
    try:
        size = archive_path.stat().st_size
        digest = sha256_file(archive_path)
        expected_size = int(spec["size_bytes"])
        expected_hash = str(spec["sha256"]).upper()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ModelPreparationError("OCR model archive metadata is incomplete") from exc
    if size != expected_size or digest != expected_hash:
        raise ModelPreparationError(
            f"OCR model archive hash mismatch: {archive_path} "
            f"(size {size}/{expected_size}, sha256 {digest}/{expected_hash})"
        )


def _download_archive(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    try:
        request = Request(url, headers={"User-Agent": "ShuaBao-release-model-preparer/1"})
        with urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
            for chunk in iter(lambda: response.read(1 << 20), b""):
                handle.write(chunk)
        os.replace(temporary, destination)
    except Exception as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ModelPreparationError(f"failed to download OCR model archive: {url}") from exc


def _safe_extract(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in member.name:
                raise ModelPreparationError(f"unsafe path in OCR archive: {member.name!r}")
            if member.issym() or member.islnk():
                raise ModelPreparationError(f"links are not allowed in OCR archive: {member.name!r}")
            if not (member.isdir() or member.isfile()):
                raise ModelPreparationError(f"special files are not allowed in OCR archive: {member.name!r}")
            target = (destination / Path(*relative.parts)).resolve()
            if os.path.commonpath((str(destination), str(target))) != str(destination):
                raise ModelPreparationError(f"unsafe path in OCR archive: {member.name!r}")
            archive.extract(member, destination)


def prepare_model(
    manifest_path: Path = DEFAULT_MANIFEST,
    models_dir: Path | None = None,
    model_name: str = MODEL_NAME,
) -> dict[str, str]:
    """Ensure the selected model exists and matches its manifest exactly."""
    manifest_path = manifest_path.resolve()
    models_dir = (models_dir or manifest_path.parent).resolve()
    entry = _load_entry(manifest_path, model_name)
    target = models_dir / model_name
    archive_spec = entry.get("archive") or {}
    archive_name = Path(str(archive_spec.get("file") or "")).name
    if not archive_name:
        raise ModelPreparationError("OCR model entry has no archive file name")
    archive_path = models_dir / archive_name

    try:
        _verify_files(target, entry)
        return {"status": "verified", "model": str(target), "archive": str(archive_path)}
    except ModelPreparationError:
        pass

    try:
        _verify_archive(archive_path, entry)
    except ModelPreparationError:
        url = str(entry.get("source_url") or "").strip()
        if not url:
            raise
        _download_archive(url, archive_path)
        _verify_archive(archive_path, entry)

    models_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shuabao_ocr_extract_", dir=models_dir) as temporary:
        extract_root = Path(temporary)
        _safe_extract(archive_path, extract_root)
        staged = extract_root / model_name
        if not staged.is_dir():
            candidates = list(extract_root.rglob(model_name))
            staged = candidates[0] if len(candidates) == 1 and candidates[0].is_dir() else staged
        _verify_files(staged, entry)
        if target.is_symlink():
            raise ModelPreparationError(f"OCR model target is a symlink: {target}")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        shutil.move(str(staged), str(target))
    _verify_files(target, entry)
    return {"status": "installed", "model": str(target), "archive": str(archive_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--models-dir", type=Path)
    parser.add_argument("--model", default=MODEL_NAME)
    args = parser.parse_args()
    try:
        result = prepare_model(args.manifest, args.models_dir, args.model)
    except (ModelPreparationError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
