# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.vision.ocr_shadow.protocol -> shuabao.vision.ocr_shadow.protocol."""
import sys
import importlib

_mod = importlib.import_module('shuabao.vision.ocr_shadow.protocol')
sys.modules[__name__] = _mod
