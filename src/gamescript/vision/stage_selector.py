# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.vision.stage_selector -> shuabao.vision.stage_selector."""
import sys
import importlib

_mod = importlib.import_module('shuabao.vision.stage_selector')
sys.modules[__name__] = _mod
