# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.mediator -> shuabao.mediator."""
import sys
import importlib

_mod = importlib.import_module('shuabao.mediator')
sys.modules[__name__] = _mod
