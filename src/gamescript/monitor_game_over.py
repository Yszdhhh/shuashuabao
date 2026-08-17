# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.monitor_game_over -> shuabao.monitor_game_over."""
import sys
import importlib

_mod = importlib.import_module('shuabao.monitor_game_over')
sys.modules[__name__] = _mod
