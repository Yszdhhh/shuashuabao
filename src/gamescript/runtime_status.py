# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.runtime_status -> shuabao.runtime_status."""
import sys
import importlib

_mod = importlib.import_module('shuabao.runtime_status')
sys.modules[__name__] = _mod
