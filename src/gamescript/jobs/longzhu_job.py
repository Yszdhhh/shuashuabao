# -*- coding: utf-8 -*-
"""Compatibility shim for gamescript.jobs.longzhu_job -> shuabao.jobs.longzhu_job."""
import sys
import importlib

_mod = importlib.import_module('shuabao.jobs.longzhu_job')
sys.modules[__name__] = _mod
