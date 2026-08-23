# -*- coding: utf-8 -*-
"""Regression tests for gamescript.* -> shuabao.* singleton aliasing.

Guards against CPython _bootstrap._find_and_load_unlocked bypass where
pre-writing sys.modules causes alias spec to be discarded and target source
to be re-executed under two distinct module objects.
"""
import subprocess
import sys
import textwrap
import pytest


@pytest.mark.parametrize("order", ["shuabao_first", "gs_first", "from_import"])
def test_gamescript_alias_singleton_execution_count_and_identity(order: str):
    """Under all three import sequences, the module source must execute exactly once

    and both module paths must point to the identical module object.
    """
    probe = textwrap.dedent(f"""
    import sys, importlib._bootstrap_external
    sys.path.insert(0, r"src")
    execs = []
    real_exec = importlib._bootstrap_external.SourceFileLoader.exec_module
    def spy(self, module):
        if "choice_policy" in getattr(module, "__name__", ""):
            execs.append(module.__name__)
        return real_exec(self, module)
    importlib._bootstrap_external.SourceFileLoader.exec_module = spy

    ORDER = "{order}"
    if ORDER == "shuabao_first":
        import shuabao.choice_policy as a
        import gamescript.choice_policy as b
    elif ORDER == "gs_first":
        import gamescript.choice_policy as a
        import shuabao.choice_policy as b
    else:
        from gamescript.choice_policy import DEFAULT_NEGATIVE_NAMES
        import shuabao.choice_policy as b
        a = sys.modules["gamescript.choice_policy"]

    assert len(execs) == 1, f"Expected 1 execution, got {{len(execs)}}: {{execs}}"
    assert a is b, "gamescript.choice_policy is not shuabao.choice_policy"
    assert sys.modules.get("gamescript.choice_policy") is b, "sys.modules alias broken"
    print("OK")
    """)
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert r.returncode == 0, f"Probe failed (stderr: {r.stderr}, stdout: {r.stdout})"
    assert "OK" in r.stdout
