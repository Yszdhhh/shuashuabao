"""Task 3：DashboardFacade 只读与配置往返面（设计规格 §6/§7，task-3-brief）。

覆盖：
- 白名单 Slot 方法面（未列方法不存在；Task 4 起 start_run/stop_run 入列）；
- get_snapshot DTO 形状与 PERSIST_DENYLIST 剔除；
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

EXPECTED_SLOTS = {
    "get_snapshot",
    "update_config",
    "update_shell",
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
    assert set(snap) == {
        "request_id", "settings_revision", "snapshot_seq", "settings", "strategy", "shell", "modes", "run",
    }
    assert "lab_focus" not in snap["settings"]
    assert snap["settings"]["click_delay_ms"] == 200
    assert snap["shell"]["theme"] == "dark"
    assert snap["shell"]["selected_mode_id"]
    assert snap["modes"], "modes 数组不得为空"
    for m in snap["modes"]:
        assert set(m) == {"id", "label", "startable", "evidence_status", "badge",
                          "blocked_reason", "visible_settings"}
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


def test_stage_target_and_hero_plan_round_trip_to_runtime_settings(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    patch = {
        "stage_targets": ["3-8"],
        "auto_reputation": True,
        "reputation_allocations": {"3": 5, "5": 2},
    }
    res = json.loads(f.update_config(json.dumps(patch)))
    assert res["ok"] is True
    assert res["settings"]["stage_targets"] == ["3-8"]
    assert res["settings"]["auto_reputation"] is True
    assert res["settings"]["reputation_allocations"] == {"3": 5, "5": 2}
    f2 = DashboardFacade(tmp_path)
    persisted = json.loads(f2.get_snapshot())["settings"]
    assert {key: persisted[key] for key in patch} == patch


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


def test_update_config_rejects_skills_over_max_without_writing(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    patch = {"skills": [f"s{i}" for i in range(10)]}
    res = json.loads(f.update_config(json.dumps(patch)))
    assert res["ok"] is False
    assert "skills" in "\n".join(res["errors"])
    assert not user_settings_path(tmp_path).exists()


def test_update_config_rejects_overlong_pair_code_without_writing(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    res = json.loads(f.update_config(json.dumps({"follow_pair_code": "x" * 25})))
    assert res["ok"] is False
    assert "follow_pair_code" in "\n".join(res["errors"])
    assert not user_settings_path(tmp_path).exists()


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
    assert json.loads(facade.window_control(json.dumps("minimize")))["ok"] is True
    assert json.loads(facade.window_control(json.dumps({"action": "close"})))["ok"] is True
    assert facade.recorded_actions == ["minimize", "close"]


def test_window_control_rejects_unknown_action(facade):
    assert json.loads(facade.window_control(json.dumps("explode")))["ok"] is False
    assert facade.recorded_actions == []


def test_window_control_without_handler_fails_closed(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    assert json.loads(f.window_control(json.dumps("close")))["ok"] is False


def test_dashboard_contract_v2_strategy_and_revision_metadata(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    initial = json.loads(f.get_snapshot())
    assert initial["request_id"] is None
    assert initial["settings_revision"] == 0
    assert initial["snapshot_seq"] == 1
    assert initial["strategy"] == {
        "skills": ["jq", "pg"],
        "bonds": ["祝福", "成长", "经济", "贪婪", "挑战"],
        "attributes": [],
        "merchant": {"enabled": False, "max_rerolls": 0, "gold_reserve": 0},
        "treasure": {"negative_allowlist": []},
    }

    result = json.loads(f.update_config(json.dumps({
        "request_id": "config-7",
        "settings_revision": 0,
        "strategy": {
            "skills": ["jq"],
            "bonds": ["祝福", "成长"],
            "attributes": ["int", "agi"],
            "merchant": {"enabled": True, "max_rerolls": 2, "gold_reserve": 100},
            "treasure": {"negative_allowlist": ["扣除金币"]},
        },
    })))
    assert result["ok"] is True
    assert result["request_id"] == "config-7"
    assert result["settings_revision"] == 1
    assert result["snapshot_seq"] == 2
    assert result["strategy"]["merchant"]["gold_reserve"] == 100


@pytest.mark.parametrize("patch", [
    {"click_delay_ms": "250"},
    {"dry_run": 1},
    {"strategy": {"skills": ["jq", 2]}},
    {"strategy": {"bonds": ["未知羁绊"]}},
    {"strategy": {"attributes": ["intelligence"]}},
    {"strategy": {"merchant": {"enabled": "true"}}},
    {"strategy": {"merchant": {"max_rerolls": True}}},
    {"strategy": {"treasure": {"negative_allowlist": [1]}}},
])
def test_dashboard_contract_v2_rejects_type_coercion_atomically(qapp, tmp_path: Path, patch):
    f = DashboardFacade(tmp_path)
    before = f.get_snapshot()
    result = json.loads(f.update_config(json.dumps(patch)))
    assert result["ok"] is False
    assert result["settings_revision"] == 0
    assert json.loads(f.get_snapshot())["settings_revision"] == 0
    assert not user_settings_path(tmp_path).exists()
    assert json.loads(before)["settings"] == json.loads(f.get_snapshot())["settings"]

def test_dashboard_contract_v2_rejects_duplicate_top_level_and_strategy(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    # Sending both top-level and strategy fields must be rejected by Facade
    patch = {
        "skills": ["jq"],
        "strategy": {"skills": ["pg"]},
    }
    result = json.loads(f.update_config(json.dumps(patch)))
    assert result["ok"] is False
    assert any("strategy 与顶层字段重复" in err for err in result["errors"])

def test_dashboard_contract_v2_pure_strategy_roundtrip(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    patch = {
        "request_id": "req-roundtrip-1",
        "settings_revision": 0,
        "strategy": {
            "skills": ["jq", "pg"],
            "bonds": ["祝福", "经济"],
            "attributes": ["str"],
            "merchant": {"enabled": True, "max_rerolls": 3, "gold_reserve": 500},
            "treasure": {"negative_allowlist": ["降低攻速"]},
        },
    }
    result = json.loads(f.update_config(json.dumps(patch)))
    assert result["ok"] is True
    assert result["errors"] == []
    assert result["strategy"]["bonds"] == ["祝福", "经济"]
    assert result["strategy"]["attributes"] == ["str"]
    assert result["strategy"]["merchant"]["gold_reserve"] == 500
    assert result["strategy"]["treasure"]["negative_allowlist"] == ["降低攻速"]

    # Verify fresh facade readback
    f2 = DashboardFacade(tmp_path)
    snap = json.loads(f2.get_snapshot())
    assert snap["strategy"]["bonds"] == ["祝福", "经济"]
    assert snap["strategy"]["attributes"] == ["str"]
    assert snap["strategy"]["merchant"]["gold_reserve"] == 500
    assert snap["strategy"]["treasure"]["negative_allowlist"] == ["降低攻速"]
