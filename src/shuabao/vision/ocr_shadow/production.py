"""Production-only OCR runtime resolution for ShuaBao LIVE.

This module intentionally contains no historical GameScript path/env fallbacks.
Development runs use a ShuaBao-owned OCR virtualenv; packaged runs require an
explicit standalone OCR worker executable.  Missing packaged runtime fails
closed instead of trying to execute ShuaBao.exe as a Python interpreter.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .client import ShadowClient


class ProductionShadowClient(ShadowClient):
    """ShadowClient with deterministic ShuaBao-only runtime discovery."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        timeout_ms: int = 1500,
        startup_timeout_ms: int = 30000,
        trace_path: str | Path | None = None,
    ) -> None:
        root = Path(repo_root).expanduser().resolve()
        executable, standalone = _resolve_production_worker(root)
        self._standalone_worker = standalone
        super().__init__(
            repo_root=root,
            python_executable=executable,
            model_dir=_resolve_production_model_dir(root),
            timeout_ms=timeout_ms,
            startup_timeout_ms=startup_timeout_ms,
            trace_path=trace_path,
            # Mark a packaged sidecar as an explicit worker command.  This
            # deliberately bypasses ShadowClient's source-package preflight,
            # which is correct for `python -m ...` development workers but not
            # for a self-contained ShuaBaoOCR.exe.
            worker_command=[str(executable)] if standalone else None,
        )


def _resolve_production_worker(repo_root: Path) -> tuple[Path, bool]:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meipass = Path(getattr(sys, "_MEIPASS", exe_dir)).resolve()
        candidates = (
            exe_dir / "vision" / "ShuaBaoOCR.exe",
            exe_dir / "ShuaBaoOCR.exe",
            meipass / "vision" / "ShuaBaoOCR.exe",
            meipass / "ShuaBaoOCR.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate, True
        raise FileNotFoundError(
            "packaged OCR runtime missing: expected ShuaBaoOCR.exe under the ShuaBao distribution"
        )

    explicit = str(os.environ.get("SHUABAO_OCR_PYTHON") or "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_file():
            return path, False
        raise FileNotFoundError(f"SHUABAO_OCR_PYTHON not found: {path}")
    roots = [
        repo_root,
        repo_root.parent,
        repo_root.parent.parent,
        repo_root.parent / "shuashuabao",
        repo_root.parent.parent / "shuashuabao",
    ]
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(
            [
                root / ".venv-ocr" / "Scripts" / "python.exe",
                root / "venv-ocr" / "Scripts" / "python.exe",
                root / "ShuaBao.venv-ocr" / "Scripts" / "python.exe",
            ]
        )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve(), False
        except OSError:
            continue
    raise FileNotFoundError(
        "ShuaBao OCR runtime missing; create .venv-ocr or set SHUABAO_OCR_PYTHON"
    )


def _resolve_production_model_dir(repo_root: Path) -> Path:
    explicit = str(os.environ.get("SHUABAO_OCR_MODEL_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meipass = Path(getattr(sys, "_MEIPASS", exe_dir)).resolve()
        for candidate in (
            exe_dir / "models" / "ocr",
            meipass / "models" / "ocr",
        ):
            if candidate.is_dir():
                return candidate
        return exe_dir / "models" / "ocr"
    return repo_root / "models" / "ocr"
