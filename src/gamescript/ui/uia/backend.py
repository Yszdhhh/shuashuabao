# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.ui.uia.backend -> shuabao.ui.uia.backend."""
import sys
import importlib

_mod = importlib.import_module('shuabao.ui.uia.backend')
sys.modules[__name__] = _mod
