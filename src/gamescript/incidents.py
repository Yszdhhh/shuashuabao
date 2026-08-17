# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.incidents -> shuabao.incidents."""
import sys
import importlib

_mod = importlib.import_module('shuabao.incidents')
sys.modules[__name__] = _mod
