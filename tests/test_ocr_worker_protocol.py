"""The OCR sidecar protocol must remain UTF-8 independent of Windows locale."""

from __future__ import annotations

import io
import json

from shuabao.vision.ocr_shadow import worker


def test_worker_emits_utf8_json_bytes(monkeypatch) -> None:  # noqa: ANN001
    buffer = io.BytesIO()

    class Stream:
        pass

    stream = Stream()
    stream.buffer = buffer
    monkeypatch.setattr(worker.sys, "stdout", stream)

    worker._emit({"type": "predict", "raw_text": "次级箭"})

    assert json.loads(buffer.getvalue().decode("utf-8"))["raw_text"] == "次级箭"
