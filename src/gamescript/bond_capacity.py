# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.bond_capacity -> shuabao.bond_capacity."""
import sys
import importlib

_mod = importlib.import_module('shuabao.bond_capacity')
sys.modules[__name__] = _mod
