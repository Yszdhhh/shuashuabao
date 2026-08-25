# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.ui.uia.model -> shuabao.ui.uia.model."""
import sys
import importlib

_mod = importlib.import_module('shuabao.ui.uia.model')
sys.modules[__name__] = _mod
