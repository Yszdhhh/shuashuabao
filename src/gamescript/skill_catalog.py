# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.skill_catalog -> shuabao.skill_catalog."""
import sys
import importlib

_mod = importlib.import_module('shuabao.skill_catalog')
sys.modules[__name__] = _mod
