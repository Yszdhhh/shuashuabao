"""Frozen distribution resolves its adjacent OCR worker and validated model."""

from __future__ import annotations

from pathlib import Path

from shuabao.vision.ocr_shadow import production


def test_frozen_bundle_resolves_worker_and_model(monkeypatch, tmp_path: Path) -> None:
    app = tmp_path / "ShuaBao.exe"
    app.touch()
    worker = tmp_path / "vision" / "ShuaBaoOCR.exe"
    worker.parent.mkdir()
    worker.touch()
    model = tmp_path / "vision" / "_internal" / "models" / "ocr"
    model.mkdir(parents=True)

    monkeypatch.setattr(production.sys, "frozen", True, raising=False)
    monkeypatch.setattr(production.sys, "executable", str(app))
    monkeypatch.setattr(production.sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)

    assert production._resolve_production_worker(tmp_path) == (worker, True)
    assert production._resolve_production_model_dir(tmp_path) == model


def test_release_script_builds_and_embeds_the_ocr_worker() -> None:
    root = Path(__file__).resolve().parents[1]
    release_script = (root / "build_release.ps1").read_text(encoding="utf-8")

    assert "ShuaBaoOCR.spec" in release_script
    assert '"dist\\$APP_ID\\vision"' in release_script
