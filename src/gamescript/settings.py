# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.settings -> shuabao.settings."""
import sys
import importlib

_mod = importlib.import_module('shuabao.settings')
sys.modules[__name__] = _mod
