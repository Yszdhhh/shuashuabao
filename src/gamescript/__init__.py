# -*- coding: utf-8 -*-
"""Backward-compatibility shim redirecting gamescript.* -> shuabao.*"""
import sys
import importlib
import importlib.util
import types

class _AliasLoader:
    """持引用别名 loader：create_module 直接返回目标模块对象。

    注意：find_spec 内绝不可提前写 sys.modules[fullname]——那会触发
    CPython _bootstrap._find_and_load_unlocked 的「模块已在 sys.modules」
    旁路，别名 spec 被丢弃、目标源码被真实 loader 二次执行（副本分裂）。
    """
    def __init__(self, mod):
        self._mod = mod
    def create_module(self, spec):
        return self._mod
    def exec_module(self, module):
        pass

class _CompatFinder:
    @classmethod
    def find_spec(cls, fullname, path, target=None):
        if fullname == "gamescript" or fullname.startswith("gamescript."):
            target_name = "shuabao" + fullname[len("gamescript"):]
            target_mod = importlib.import_module(target_name)
            return importlib.util.spec_from_loader(fullname, _AliasLoader(target_mod))
        return None

if not any(isinstance(f, type) and f.__name__ == "_CompatFinder" for f in sys.meta_path):
    sys.meta_path.insert(0, _CompatFinder)

import shuabao
sys.modules["gamescript"] = shuabao
