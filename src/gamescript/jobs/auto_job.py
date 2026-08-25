# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.jobs.auto_job -> shuabao.jobs.auto_job."""
import sys
import importlib

_mod = importlib.import_module('shuabao.jobs.auto_job')
sys.modules[__name__] = _mod
