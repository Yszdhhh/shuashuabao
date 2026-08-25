# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.choice_policy -> shuabao.choice_policy."""
import sys
import importlib

_mod = importlib.import_module('shuabao.choice_policy')
sys.modules[__name__] = _mod
