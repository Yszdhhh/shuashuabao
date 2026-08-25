# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.player_profile -> shuabao.player_profile."""
import sys
import importlib

_mod = importlib.import_module('shuabao.player_profile')
sys.modules[__name__] = _mod
