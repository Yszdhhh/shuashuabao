# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.vision.ocr_shadow.worker -> shuabao.vision.ocr_shadow.worker."""
import sys
import importlib

_mod = importlib.import_module('shuabao.vision.ocr_shadow.worker')
sys.modules[__name__] = _mod
