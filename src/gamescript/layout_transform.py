# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.layout_transform -> shuabao.layout_transform."""
import sys
import importlib

_mod = importlib.import_module('shuabao.layout_transform')
sys.modules[__name__] = _mod
