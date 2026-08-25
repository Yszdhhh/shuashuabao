"""Task 3：DashboardFacade 只读与配置往返面（设计规格 §6/§7，task-3-brief）。

覆盖：
- 白名单 Slot 方法面（未列方法不存在；Task 4 起 start_run/stop_run 入列）；
- get_snapshot / get_modes DTO 形状与 PERSIST_DENYLIST 剔除；
- update_config 合法字段更新落盘、非法字段过滤且不落盘、_shell 不被擦除；
- update_shell 白名单字段校验与持久化；
- validate_preflight 真实调用 desktop_may_start / live_lock_busy 的 fail-closed 行为；
- window_control 仅放行 minimize/close。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QLockFile, QMetaMethod

from shuabao.paths import live_lock_path, user_settings_path
from shuabao.shell.dashboard_facade import (
    PREFLIGHT_CHECK_IDS,
    DashboardFacade,
)
from shuabao.shell.mode_catalog import desktop_may_start

EXPECTED_SLOTS = {
    "get_snapshot",
    "update_config",
    "update_shell",
    "get_modes",
    "validate_preflight",
    "window_control",
    "start_run",
    "stop_run",
}
EXPECTED_SIGNALS = {"snapshot_changed", "run_status_changed", "log_appended"}


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


@pytest.fixture()
def facade(qapp, tmp_path: Path):
    actions: list[str] = []
    f = DashboardFacade(
        tmp_path,
        on_minimize=lambda: actions.append("minimize"),
        on_close=lambda: actions.append("close"),
    )
    f.recorded_actions = actions
    return f


def _slot_names(obj) -> set[str]:
    meta = obj.metaObject()
    out: set[str] = set()
    for i in range(meta.methodCount()):
        m: QMetaMethod = meta.method(i)
        if m.methodType() == QMetaMethod.Method.Slot:
            out.add(bytes(m.name()).decode())
    return out


def _signal_names(obj) -> set[str]:
    meta = obj.metaObject()
    out: set[str] = set()
    for i in range(meta.methodCount()):
        m: QMetaMethod = meta.method(i)
        if m.methodType() == QMetaMethod.Method.Signal:
            out.add(bytes(m.name()).decode())
    return out


# ---------------------------------------------------------------- 白名单方法面


def test_whitelist_surface(facade):
    slots = _slot_names(facade)
    assert EXPECTED_SLOTS <= slots
    # Qt 自带槽之外不允许出现其他自定义槽。
    # QTimer.timeout.connect 会把 _poll_runtime 注册为动态槽，属实现细节而非桥面。
    qt_builtin = {"deleteLater", "_poll_runtime"}
    assert slots - EXPECTED_SLOTS <= qt_builtin
    signals = _signal_names(facade)
    assert EXPECTED_SIGNALS <= signals


# ---------------------------------------------------------------- get_snapshot


def test_snapshot_shape_strips_denylist(qapp, tmp_path: Path):
    path = user_settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"click_delay_ms": 200, "lab_focus": "boss", "_shell": {"theme": "dark"}}),
        encoding="utf-8",
    )
    f = DashboardFacade(tmp_path)
    snap = json.loads(f.get_snapshot())
    assert set(snap) == {"settings", "shell", "modes", "run"}
    assert "lab_focus" not in snap["settings"]
    assert snap["settings"]["click_delay_ms"] == 200
    assert snap["shell"]["theme"] == "dark"
    assert snap["shell"]["selected_mode_id"]
    assert snap["modes"], "modes 数组不得为空"
    for m in snap["modes"]:
        assert {"id", "label", "startable", "enabled", "desktop_start",
                "evidence_status", "badge", "blocked_reason",
                "visible_settings"} <= set(m)
    assert snap["run"]["state"] == "IDLE"


# ---------------------------------------------------------------- update_config


def test_update_config_valid_fields_persist(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    emitted = []
    f.snapshot_changed.connect(emitted.append)
    res = json.loads(f.update_config(json.dumps({"click_delay_ms": 250, "dry_run": True})))
    assert res["ok"] is True
    assert res["errors"] == []
    assert res["settings"]["click_delay_ms"] == 250
    assert res["settings"]["dry_run"] is True
    assert len(emitted) == 1
    snap = json.loads(emitted[0])
    assert snap["settings"]["click_delay_ms"] == 250
    on_disk = json.loads(user_settings_path(tmp_path).read_text(encoding="utf-8"))
    assert on_disk["click_delay_ms"] == 250
    # 重启往返：新实例从磁盘读回。
    f2 = DashboardFacade(tmp_path)
    assert json.loads(f2.get_snapshot())["settings"]["click_delay_ms"] == 250


def test_update_config_filters_invalid_and_never_writes(qapp, tmp_path: Path):
    path = user_settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    before = json.dumps({"click_delay_ms": 120, "_shell": {"theme": "dark"}}, ensure_ascii=False)
    path.write_text(before, encoding="utf-8")

    f = DashboardFacade(tmp_path)
    bad = {
        "click_delay_ms": "not-a-number",  # 非法类型
        "no_such_field": 1,                # 未知字段
        "lab_focus": "boss",               # PERSIST_DENYLIST
        "_shell": {"theme": "dark"},       # 外壳保留键不得经 config 面改写
    }
    res = json.loads(f.update_config(json.dumps(bad)))
    assert res["ok"] is False
    joined = "\n".join(res["errors"])
    for key in bad:
        assert key in joined
    assert path.read_text(encoding="utf-8") == before, "非法 patch 不得落盘"
    # 快照仍为旧值。
    assert json.loads(f.get_snapshot())["settings"]["click_delay_ms"] == 120


def test_update_config_preserves_shell_bundle(qapp, tmp_path: Path):
    path = user_settings_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    shell_extras = {"theme": "dark", "bond_scheme": ["a", "b"], "attr_route": ["力量"]}
    path.write_text(
        json.dumps({"click_delay_ms": 120, "_shell": shell_extras}, ensure_ascii=False),
        encoding="utf-8",
    )
    f = DashboardFacade(tmp_path)
    res = json.loads(f.update_config(json.dumps({"click_delay_ms": 300})))
    assert res["ok"] is True
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["_shell"] == shell_extras, "_shell 不得被配置保存擦除"
    assert on_disk["click_delay_ms"] == 300


def test_update_config_skills_truncated_to_max(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    patch = {"skills": [f"s{i}" for i in range(10)]}
    res = json.loads(f.update_config(json.dumps(patch)))
    assert len(res["settings"]["skills"]) == 4  # MAX_SELECTED_SKILLS


# ---------------------------------------------------------------- update_shell


def test_update_shell_valid_and_persisted(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    res = json.loads(f.update_shell(json.dumps({"theme": "dark", "selected_mode_id": "normal_farm"})))
    assert res["ok"] is True
    assert res["errors"] == []
    assert res["shell"] == {"theme": "dark", "selected_mode_id": "normal_farm"}
    on_disk = json.loads(user_settings_path(tmp_path).read_text(encoding="utf-8"))
    assert on_disk["_shell"]["theme"] == "dark"
    assert on_disk["_shell"]["selected_mode_id"] == "normal_farm"


def test_update_shell_rejects_out_of_whitelist(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    res = json.loads(f.update_shell(json.dumps({"theme": "neon", "selected_mode_id": "nope"})))
    assert res["ok"] is False
    joined = "\n".join(res["errors"])
    assert "theme" in joined and "selected_mode_id" in joined
    assert not user_settings_path(tmp_path).exists(), "非法 shell patch 不得落盘"


# ---------------------------------------------------------------- get_modes


def test_get_modes_matches_catalog(facade):
    modes = json.loads(facade.get_modes())
    ids = [m["id"] for m in modes]
    assert ids
    for m in modes:
        assert m["startable"] == desktop_may_start(m["id"])
        assert bool(m["blocked_reason"]) != m["startable"]
        assert m["badge"]
        assert isinstance(m["visible_settings"], list)


# ---------------------------------------------------------------- preflight


def test_preflight_ok_for_startable_mode(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    f.update_config(json.dumps({"skills": ["s1", "s2"]}))
    pre = json.loads(f.validate_preflight(json.dumps({"mode_id": "normal_farm"})))
    assert pre["ok"] is True
    assert pre["blocked_reason"] == ""
    assert {c["id"] for c in pre["checks"]} == set(PREFLIGHT_CHECK_IDS)
    assert all(c["ok"] for c in pre["checks"])


def test_preflight_fail_closed_unknown_mode(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    pre = json.loads(f.validate_preflight(json.dumps({"mode_id": "does_not_exist"})))
    assert pre["ok"] is False
    assert pre["blocked_reason"]
    assert any(c["id"] == "mode_enabled" and not c["ok"] for c in pre["checks"])


def test_preflight_blocks_when_live_lock_busy(qapp, tmp_path: Path):
    lock_dir = live_lock_path(tmp_path).parent
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(live_lock_path(tmp_path)))
    assert lock.tryLock(0)
    try:
        f = DashboardFacade(tmp_path)
        pre = json.loads(f.validate_preflight(json.dumps("normal_farm")))
        assert pre["ok"] is False
        assert any(c["id"] == "live_lock" and not c["ok"] for c in pre["checks"])
    finally:
        lock.unlock()


def test_preflight_empty_skills_blocked(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    f.update_config(json.dumps({"skills": []}))
    pre = json.loads(f.validate_preflight(json.dumps("normal_farm")))
    assert pre["ok"] is False


def test_preflight_follow_pair_code_too_long(qapp, tmp_path: Path):
    # Settings._from_dict 在载入/写入两侧都会把配对码截断到 24；
    # 此处用 replace 直接构造超长值，单测 preflight 自身的 fail-closed 复核。
    f = DashboardFacade(tmp_path)
    f._settings = replace(f._settings, skills=["s1"], follow_pair_code="x" * 25)
    pre = json.loads(f.validate_preflight(json.dumps("follow_team")))
    assert pre["ok"] is False
    assert any(c["id"] == "follow_pair_code" and not c["ok"] for c in pre["checks"])


# ---------------------------------------------------------------- window_control


def test_window_control_dispatches_minimize_and_close(facade):
    assert json.loads(facade.window_control(json.dumps("minimize"))) == {"ok": True}
    assert json.loads(facade.window_control(json.dumps({"action": "close"}))) == {"ok": True}
    assert facade.recorded_actions == ["minimize", "close"]


def test_window_control_rejects_unknown_action(facade):
    assert json.loads(facade.window_control(json.dumps("explode")))["ok"] is False
    assert facade.recorded_actions == []


def test_window_control_without_handler_fails_closed(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    assert json.loads(f.window_control(json.dumps("close")))["ok"] is False
