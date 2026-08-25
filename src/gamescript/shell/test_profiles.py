# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.shell.test_profiles -> shuabao.shell.test_profiles."""
import sys
import importlib

_mod = importlib.import_module('shuabao.shell.test_profiles')
sys.modules[__name__] = _mod
