# -*- coding: utf-8 -*-
"""Backward-compatibility shim redirecting gamescript.* -> shuabao.*"""
import sys
import importlib
import types

class _CompatFinder:
    @classmethod
    def find_spec(cls, fullname, path, target=None):
        if fullname == "gamescript" or fullname.startswith("gamescript."):
            target_name = "shuabao" + fullname[len("gamescript"):]
            target_mod = importlib.import_module(target_name)
            sys.modules[fullname] = target_mod
            return importlib.util.find_spec(target_name)
        return None

if not any(isinstance(f, type) and f.__name__ == "_CompatFinder" for f in sys.meta_path):
    sys.meta_path.insert(0, _CompatFinder)

import shuabao
sys.modules["gamescript"] = shuabao
