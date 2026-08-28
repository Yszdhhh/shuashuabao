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
    assert "prepare_ocr_model.py" in release_script
    assert "主程序打包失败" in release_script


def test_ocr_packaging_uses_one_open_cv_distribution() -> None:
    root = Path(__file__).resolve().parents[1]
    lock = (root / "requirements-ocr.lock").read_text(encoding="utf-8")
    requirements = (root / "requirements-ocr.txt").read_text(encoding="utf-8")
    spec = (root / "ShuaBaoOCR.spec").read_text(encoding="utf-8")

    assert "opencv-contrib-python==4.10.0.84" in lock
    assert "opencv-contrib-python==4.10.0.84" in requirements
    assert "opencv-python==" not in requirements
    assert "opencv-python==" not in lock
    assert '"opencv-contrib-python"' in spec
    assert '"opencv-python"' not in spec
