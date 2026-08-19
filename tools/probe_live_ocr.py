import sys
from pathlib import Path
from shuabao.vision.ocr_shadow.production import ProductionShadowClient

c = ProductionShadowClient(repo_root=Path.cwd())
print("LIVE OCR START:", c.start())
print("LIVE OCR PING:", c.ping())
print("LIVE OCR HEALTH:", c.health())
c.close()
print("LIVE OCR CLOSED")
