# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.ui.uia.selector -> shuabao.ui.uia.selector."""
import sys
import importlib

_mod = importlib.import_module('shuabao.ui.uia.selector')
sys.modules[__name__] = _mod
