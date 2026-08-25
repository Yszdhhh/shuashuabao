# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.input.keyboard_mouse -> shuabao.input.keyboard_mouse."""
import sys
import importlib

_mod = importlib.import_module('shuabao.input.keyboard_mouse')
sys.modules[__name__] = _mod
