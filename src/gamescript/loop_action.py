# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.loop_action -> shuabao.loop_action."""
import sys
import importlib

_mod = importlib.import_module('shuabao.loop_action')
sys.modules[__name__] = _mod
