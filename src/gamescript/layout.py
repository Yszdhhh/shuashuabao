# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.layout -> shuabao.layout."""
import sys
import importlib

_mod = importlib.import_module('shuabao.layout')
sys.modules[__name__] = _mod
