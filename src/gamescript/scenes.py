# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.scenes -> shuabao.scenes."""
import sys
import importlib

_mod = importlib.import_module('shuabao.scenes')
sys.modules[__name__] = _mod
