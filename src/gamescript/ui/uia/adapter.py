# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.ui.uia.adapter -> shuabao.ui.uia.adapter."""
import sys
import importlib

_mod = importlib.import_module('shuabao.ui.uia.adapter')
sys.modules[__name__] = _mod
