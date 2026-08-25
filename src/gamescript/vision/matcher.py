# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.vision.matcher -> shuabao.vision.matcher."""
import sys
import importlib

_mod = importlib.import_module('shuabao.vision.matcher')
sys.modules[__name__] = _mod
