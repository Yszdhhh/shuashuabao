# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.vision.capture -> shuabao.vision.capture."""
import sys
import importlib

_mod = importlib.import_module('shuabao.vision.capture')
sys.modules[__name__] = _mod
