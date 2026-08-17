# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.input.emergency_stop -> shuabao.input.emergency_stop."""
import sys
import importlib

_mod = importlib.import_module('shuabao.input.emergency_stop')
sys.modules[__name__] = _mod
