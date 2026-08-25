# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.interaction_surface -> shuabao.interaction_surface."""
import sys
import importlib

_mod = importlib.import_module('shuabao.interaction_surface')
sys.modules[__name__] = _mod
