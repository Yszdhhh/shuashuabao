# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.shell.main_window -> shuabao.shell.main_window."""
import sys
import importlib

_mod = importlib.import_module('shuabao.shell.main_window')
sys.modules[__name__] = _mod
