# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.shell.runner_service -> shuabao.shell.runner_service."""
import sys
import importlib

_mod = importlib.import_module('shuabao.shell.runner_service')
sys.modules[__name__] = _mod
