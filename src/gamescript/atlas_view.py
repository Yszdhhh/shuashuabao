# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.atlas_view -> shuabao.atlas_view."""
import sys
import importlib

_mod = importlib.import_module('shuabao.atlas_view')
sys.modules[__name__] = _mod
