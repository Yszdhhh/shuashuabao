# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.merchant_scanner -> shuabao.merchant_scanner."""
import sys
import importlib

_mod = importlib.import_module('shuabao.merchant_scanner')
sys.modules[__name__] = _mod
