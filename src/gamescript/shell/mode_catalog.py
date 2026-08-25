# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.shell.mode_catalog -> shuabao.shell.mode_catalog."""
import sys
import importlib

_mod = importlib.import_module('shuabao.shell.mode_catalog')
sys.modules[__name__] = _mod
