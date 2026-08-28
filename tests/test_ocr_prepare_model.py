"""Offline tests for the reproducible OCR model preparation contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import prepare_ocr_model as preparer  # noqa: E402


def test_prepare_model_extracts_and_reuses_verified_archive(tmp_path: Path) -> None:
    models_dir = tmp_path / "models" / "ocr"
    source = tmp_path / "source" / preparer.MODEL_NAME
    source.mkdir(parents=True)
    payloads = {
        "inference.json": b"{}",
        "inference.pdiparams": b"params",
        "inference.yml": b"yaml",
    }
    for name, payload in payloads.items():
        (source / name).write_bytes(payload)

    archive = models_dir / "model.tar"
    archive.parent.mkdir(parents=True)
    with tarfile.open(archive, "w") as handle:
        handle.add(source, arcname=preparer.MODEL_NAME)

    files = {
        name: {
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest().upper(),
        }
        for name, payload in payloads.items()
    }
    manifest = tmp_path / "MODEL_MANIFEST.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "models": [
                    {
                        "name": preparer.MODEL_NAME,
                        "source_url": "https://example.invalid/model.tar",
                        "archive": {"file": "models/ocr/model.tar", "sha256": preparer.sha256_file(archive), "size_bytes": archive.stat().st_size},
                        "files": files,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    first = preparer.prepare_model(manifest, models_dir)
    assert first["status"] == "installed"
    for name in payloads:
        assert (models_dir / preparer.MODEL_NAME / name).read_bytes() == payloads[name]

    second = preparer.prepare_model(manifest, models_dir)
    assert second["status"] == "verified"
