# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.vision.ocr_shadow.client -> shuabao.vision.ocr_shadow.client."""
import sys
import importlib

_mod = importlib.import_module('shuabao.vision.ocr_shadow.client')
sys.modules[__name__] = _mod
