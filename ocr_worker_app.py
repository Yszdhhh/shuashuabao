"""Standalone entrypoint for the packaged ShuaBao OCR sidecar."""

from shuabao.vision.ocr_shadow.worker import main


if __name__ == "__main__":
    raise SystemExit(main())
