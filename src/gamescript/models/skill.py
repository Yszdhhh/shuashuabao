# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.models.skill -> shuabao.models.skill."""
import sys
import importlib

_mod = importlib.import_module('shuabao.models.skill')
sys.modules[__name__] = _mod
