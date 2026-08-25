# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.ui.uia.mappings -> shuabao.ui.uia.mappings."""
import sys
import importlib

_mod = importlib.import_module('shuabao.ui.uia.mappings')
sys.modules[__name__] = _mod
