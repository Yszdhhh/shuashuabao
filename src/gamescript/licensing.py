# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.licensing -> shuabao.licensing."""
import sys
import importlib

_mod = importlib.import_module('shuabao.licensing')
sys.modules[__name__] = _mod
