# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.habit_preference -> shuabao.habit_preference."""
import sys
import importlib

_mod = importlib.import_module('shuabao.habit_preference')
sys.modules[__name__] = _mod
