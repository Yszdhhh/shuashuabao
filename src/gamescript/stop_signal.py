# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.stop_signal -> shuabao.stop_signal."""
import sys
import importlib

_mod = importlib.import_module('shuabao.stop_signal')
sys.modules[__name__] = _mod
