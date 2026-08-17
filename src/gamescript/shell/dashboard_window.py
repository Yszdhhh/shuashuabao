# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.shell.dashboard_window -> shuabao.shell.dashboard_window."""
import sys
import importlib

_mod = importlib.import_module('shuabao.shell.dashboard_window')
sys.modules[__name__] = _mod
