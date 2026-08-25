# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.ui.uia.source -> shuabao.ui.uia.source."""
import sys
import importlib

_mod = importlib.import_module('shuabao.ui.uia.source')
sys.modules[__name__] = _mod
