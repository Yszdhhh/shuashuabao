# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.shell.core03_preview -> shuabao.shell.core03_preview."""
import sys
import importlib

_mod = importlib.import_module('shuabao.shell.core03_preview')
sys.modules[__name__] = _mod
