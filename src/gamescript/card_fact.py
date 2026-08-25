# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.card_fact -> shuabao.card_fact."""
import sys
import importlib

_mod = importlib.import_module('shuabao.card_fact')
sys.modules[__name__] = _mod
