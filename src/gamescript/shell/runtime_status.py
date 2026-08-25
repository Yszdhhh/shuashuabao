# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.shell.runtime_status -> shuabao.shell.runtime_status."""
import sys
import importlib

_mod = importlib.import_module('shuabao.shell.runtime_status')
sys.modules[__name__] = _mod
