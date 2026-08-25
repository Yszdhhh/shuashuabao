# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.vision.choice_ocr -> shuabao.vision.choice_ocr."""
import sys
import importlib

_mod = importlib.import_module('shuabao.vision.choice_ocr')
sys.modules[__name__] = _mod
