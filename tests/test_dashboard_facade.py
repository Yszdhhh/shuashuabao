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
import sys
import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QLockFile, QMetaMethod
from PySide6.QtWidgets import QApplication

from shuabao.paths import live_lock_path, user_settings_path
from shuabao.settings import Settings
from shuabao.choice_policy import (
    PANEL_BOND,
    PanelCandidates,
    PolicyAction,
    SlotCandidate,
    assemble_policy_settings,
    choose_action,
)
from shuabao.mediator import Mediator
from shuabao.shell.dashboard_facade import (
    PREFLIGHT_CHECK_IDS,
    DashboardFacade,
    _mode_evidence,
)

EXPECTED_SLOTS = {
    "get_snapshot",
    "update_config",
    "update_shell",
    "validate_preflight",
    "window_control",
    "set_window_layout",
    "start_run",
    "stop_run",
    "activate_subscription",
    "refresh_subscription_status",
    "get_bridge_info",
}
EXPECTED_SIGNALS = {"snapshot_changed", "run_status_changed", "log_appended"}
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def facade(qapp, tmp_path: Path):
    actions: list[str] = []
    layouts: list[str] = []
    f = DashboardFacade(
        tmp_path,
        on_minimize=lambda: actions.append("minimize"),
        on_close=lambda: actions.append("close"),
        on_layout=lambda layout, **kw: layouts.append((layout, kw["height"]) if kw else layout),
    )
    f.recorded_actions = actions
    f.recorded_layouts = layouts
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
        "request_id", "settings_revision", "snapshot_seq", "settings", "strategy", "shell", "modes", "run", "subscription",
    }
    assert "lab_focus" not in snap["settings"]
    assert snap["settings"]["click_delay_ms"] == 200
    assert snap["shell"]["theme"] == "dark"
    assert snap["shell"]["selected_mode_id"]
    assert snap["modes"], "modes 数组不得为空"
    for m in snap["modes"]:
        assert set(m) == {"id", "label", "startable", "evidence_status", "current_evidence", "badge",
                          "blocked_reason", "visible_settings"}
        assert m["current_evidence"]["status"] in {"PASS", "BLOCKED", "MISSING", "STALE"}
    assert snap["run"]["state"] == "IDLE"


def test_bridge_info_exposes_versioned_required_surface(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    info = json.loads(f.get_bridge_info())
    assert info["ok"] is True
    assert info["schema_version"] == 2
    assert "activate_subscription" in info["required_methods"]
    assert "get_bridge_info" in info["required_methods"]
    assert set(info["required_signals"]) == EXPECTED_SIGNALS


def test_snapshot_does_not_probe_subscription_network_before_preflight(monkeypatch, qapp, tmp_path: Path):
    calls = 0

    def fail_probe():
        nonlocal calls
        calls += 1
        raise AssertionError("snapshot painting must not perform entitlement I/O")

    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_LICENSE_KEY", "cached-key")
    monkeypatch.setattr("shuabao.shell.dashboard_facade.check_start_permission", fail_probe)
    f = DashboardFacade(tmp_path)
    assert json.loads(f.get_snapshot())["subscription"]["status"] == "正在校验"
    assert calls == 0


def test_current_pass_evidence_requires_matching_release_artifacts(tmp_path: Path):
    """A green evidence label cannot outlive its manifest or EXE bytes."""
    import hashlib
    from shuabao.release_signing import canonical_manifest_sha256
    package = tmp_path / "dist" / "ShuaBao"
    package.mkdir(parents=True)
    exe = package / "ShuaBao.exe"
    exe.write_bytes(b"current-exe")
    manifest = package / "release_manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": 1, "source_sha": "source-a", "files": []}),
        encoding="utf-8",
    )
    config = tmp_path / "config"
    config.mkdir()
    config.joinpath("mode_evidence.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "modes": {
                    "normal_farm": {
                        "status": "PASS",
                        "source_sha": "source-a",
                        "release_manifest_sha256": canonical_manifest_sha256(json.loads(manifest.read_text(encoding="utf-8"))),
                        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    evidence = _mode_evidence("normal_farm", tmp_path)
    assert evidence["status"] == "STALE"
    assert "发行清单" in evidence["reason"]


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


def test_update_config_accepts_card_whitelist_once(qapp, tmp_path: Path):
    """高级卡组展开后只经顶层 cards 写入，不能与 strategy 字段冲突。"""
    f = DashboardFacade(tmp_path)
    res = json.loads(f.update_config(json.dumps({"cards": ["海盗", "海盗宝藏"]})))
    assert res["ok"] is True
    assert res["errors"] == []
    assert res["settings"]["cards"] == ["海盗", "海盗宝藏"]
    assert res["strategy"]["cards"] == ["海盗", "海盗宝藏"]


def test_dashboard_bonds_drive_the_live_hard_whitelist(qapp, tmp_path: Path):
    """看板保存的羁绊必须成为每局决策白名单，不能被旧版“祝福必拿”越过。"""
    f = DashboardFacade(tmp_path)
    res = json.loads(f.update_config(json.dumps({
        "bond_must_take": [],
        "bond_whitelist_mode": "hard",
        "cards": ["海盗"],
        "strategy": {"bonds": ["成长"]},
    })))
    assert res["ok"] is True

    policy = assemble_policy_settings(
        settings=f._settings,
        skill_labels={},
        fetter_labels={},
        policy_doc={"bond": {"whitelist_mode": "soft", "must_take_names": []}},
    )
    assert policy.bond_presets == ("成长", "海盗")
    from shuabao.choice_policy import DEFAULT_BOND_MUST_TAKE
    assert policy.bond_must_take == DEFAULT_BOND_MUST_TAKE
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(
            SlotCandidate(index=0, name="祝福", confidence=.99, rarity="red"),
            SlotCandidate(index=1, name="成长之根", confidence=.99, rarity="white"),
            SlotCandidate(index=2, name="海盗", confidence=.99, rarity="purple"),
        ),
        settings=policy,
    ))
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0)


def test_template_mode_uses_saved_bond_labels_as_card_anchors(qapp, tmp_path: Path):
    """未启用 OCR 的打包运行仍要把看板中文选择还原为 cards 模板短码。"""
    f = DashboardFacade(tmp_path)
    assert json.loads(f.update_config(json.dumps({
        "cards": ["法术", "异火"],
        "strategy": {"bonds": ["成长"]},
    })))["ok"] is True
    mediator = Mediator(f._settings, ROOT)
    assert mediator._bond_template_preferences() == ["chengzhang", "fashu", "yihuo"]


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


def test_hitch_settings_and_search_prefix_round_trip(qapp, tmp_path: Path):
    """验证自定义搜房词（支持多词与中文，如 4,3,速）、Boss 设置与局数端到端往返。"""
    fallback = Settings()
    # 1. 验证 Settings.validate_patch 对中文与多词搜房词的放行规则
    assert Settings.validate_patch({"hitch_stage_prefix": "4,3,速"}, fallback) == []
    assert Settings.validate_patch({"hitch_stage_prefix": "速,4,刷,秘境"}, fallback) == []
    assert Settings.validate_patch({"hitch_stage_prefix": "a" * 64}, fallback) == []
    assert len(Settings.validate_patch({"hitch_stage_prefix": "a" * 65}, fallback)) > 0
    assert len(Settings.validate_patch({"hitch_stage_prefix": "   "}, fallback)) > 0
    assert Settings.validate_patch({"cjb_boss": "祖尔格拉布", "sgzx_boss": "麦迪文"}, fallback) == []
    assert Settings.validate_patch({"hitch_cycle_num": 0, "follow_cycle_num": 0}, fallback) == []
    assert Settings.validate_patch({"hitch_cycle_num": 100, "follow_cycle_num": 100}, fallback) == []
    assert Settings.validate_patch({"hitch_after_goal": "solo"}, fallback) == []
    assert Settings.validate_patch({"hitch_after_goal": "arch"}, fallback) == []
    assert Settings.validate_patch({"hitch_after_goal": "end"}, fallback) == []
    assert Settings.validate_patch({"follow_after_room": "solo"}, fallback) == []
    assert Settings.validate_patch({"follow_after_room": "hitch"}, fallback) == []
    assert Settings.validate_patch({"follow_after_room": "arch"}, fallback) == []

    # 2. 经 DashboardFacade.update_config 写入与落盘验证
    f = DashboardFacade(tmp_path)
    patch = {
        "hitch_stage_prefix": "4,3,速",
        "cjb_boss": "传家宝首领",
        "sgzx_boss": "时光之穴首领",
        "hitch_cycle_num": 0,
        "follow_cycle_num": 50,
        "hitch_after_goal": "arch",
        "follow_after_room": "hitch",
    }
    res = json.loads(f.update_config(json.dumps(patch)))
    assert res["ok"] is True
    assert res["errors"] == []
    for k, v in patch.items():
        assert res["settings"][k] == v

    # 3. 跨实例重读验证
    f2 = DashboardFacade(tmp_path)
    snap = json.loads(f2.get_snapshot())["settings"]
    for k, v in patch.items():
        assert snap[k] == v


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


def _signed_frozen_package(tmp_path: Path, monkeypatch) -> Path:
    import base64
    import hashlib

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from shuabao.shell import dashboard_facade as facade_module

    package = tmp_path / "ShuaBao"
    package.mkdir()
    files = []
    for relative, payload in (
        ("config/entitlement_public_keys.json", b'{"keys": {}}'),
        ("vision/_internal/models/ocr/MODEL_MANIFEST.json", b"{}"),
        ("ShuaBao.exe", b"frozen-shuabao-exe"),
    ):
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        files.append({
            "path": relative,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    manifest = {
        "manifest_signature_status": "SIGNED",
        "schema_version": 1,
        "source_sha": "b" * 40,
        "bridge_schema_version": 2,
        "release_channel": "external-beta",
        "files": files,
    }
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    (package / "release_manifest.json").write_bytes(canonical)
    private = Ed25519PrivateKey.generate()
    envelope = {
        "schema_version": 1,
        "algorithm": "Ed25519",
        "key_id": "manifest",
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "signature": base64.urlsafe_b64encode(private.sign(canonical)).rstrip(b"=").decode("ascii"),
    }
    (package / "release_manifest.json.sig").write_text(json.dumps(envelope), encoding="utf-8")
    (package / "build_identity.json").write_text(
        json.dumps({"exe_name": "ShuaBao.exe", "source_sha": "display-only"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        facade_module, "PINNED_MANIFEST_PUBLIC_KEYS", {"manifest": private.public_key()}
    )
    return package


def test_frozen_preflight_passes_on_signed_snapshot(qapp, tmp_path: Path, monkeypatch):
    from shuabao.shell import dashboard_facade as facade_module
    from shuabao.shell.runner_service import RunnerService

    package = _signed_frozen_package(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(package / "ShuaBao.exe"))
    ok, detail = facade_module._build_identity_preflight(
        package, RunnerService(tmp_path, package)
    )
    assert ok, detail
    assert "source_sha=" + "b" * 40 in detail
    assert "release_channel=external-beta" in detail
    assert "bridge_schema=2" in detail


def test_frozen_preflight_fails_closed_without_trust_anchor(qapp, tmp_path: Path, monkeypatch):
    from shuabao.shell import dashboard_facade as facade_module
    from shuabao.shell.runner_service import RunnerService

    package = _signed_frozen_package(tmp_path, monkeypatch)
    monkeypatch.setattr(facade_module, "PINNED_MANIFEST_PUBLIC_KEYS", {})
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(package / "ShuaBao.exe"))
    ok, detail = facade_module._build_identity_preflight(
        package, RunnerService(tmp_path, package)
    )
    assert not ok
    assert "MANIFEST_TRUST_ANCHOR_MISSING" in detail


def test_current_source_sha_does_not_spawn_git_without_repo(tmp_path: Path, monkeypatch):
    from shuabao.shell import dashboard_facade as facade_module
    from shuabao.shell import live_execute

    def boom(*_args, **_kwargs):
        raise AssertionError("git must not spawn without a checkout")

    monkeypatch.setattr(live_execute.subprocess, "run", boom)
    assert facade_module._current_source_sha(tmp_path) == ""


def test_frozen_current_source_sha_skips_git_even_with_dot_git(tmp_path: Path, monkeypatch):
    from shuabao.shell import dashboard_facade as facade_module
    from shuabao.shell import live_execute

    (tmp_path / ".git").mkdir()

    def boom(*_args, **_kwargs):
        raise AssertionError("frozen runtime must not spawn git")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(live_execute.subprocess, "run", boom)
    assert facade_module._current_source_sha(tmp_path) == ""


def test_frozen_preflight_reuses_verify_cache_with_live_identity(qapp, tmp_path: Path, monkeypatch):
    from shuabao import release_signing as rs
    from shuabao.shell import dashboard_facade as facade_module
    from shuabao.shell import live_execute
    from shuabao.shell.runner_service import RunnerService

    rs.clear_packaged_release_verify_cache()
    package = _signed_frozen_package(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(package / "ShuaBao.exe"))
    monkeypatch.setattr(rs, "PINNED_MANIFEST_PUBLIC_KEYS", facade_module.PINNED_MANIFEST_PUBLIC_KEYS)
    calls = {"n": 0}
    real = rs._verify_packaged_release

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(rs, "_verify_packaged_release", counted)
    ok, detail = facade_module._build_identity_preflight(
        package, RunnerService(tmp_path, package)
    )
    identity = live_execute._live_identity(package)
    assert ok, detail
    assert identity.packaged is True
    assert identity.source_sha == "b" * 40
    assert calls["n"] == 1


def test_frozen_preflight_ignores_sidecar_when_signature_missing(qapp, tmp_path: Path, monkeypatch):
    from shuabao.shell import dashboard_facade as facade_module
    from shuabao.shell.runner_service import RunnerService

    package = _signed_frozen_package(tmp_path, monkeypatch)
    (package / "release_manifest.json.sig").unlink()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(package / "ShuaBao.exe"))
    ok, detail = facade_module._build_identity_preflight(
        package, RunnerService(tmp_path, package)
    )
    assert not ok
    assert "MANIFEST_SIGNATURE_MISSING" in detail


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


def test_set_window_layout_only_allows_ephemeral_known_layouts(facade):
    assert json.loads(facade.set_window_layout(json.dumps({"layout": "chooser"})))["ok"] is True
    for layout in ("chooser-solo", "chooser-team"):
        assert json.loads(facade.set_window_layout(json.dumps({"layout": layout}))).get("ok") is True
    assert facade.recorded_layouts == ["chooser", "chooser-solo", "chooser-team"]
    assert json.loads(facade.set_window_layout(json.dumps({"layout": "unknown"})))["ok"] is False


def test_set_window_layout_compact_requires_a_sane_measured_height(facade):
    ok = json.loads(facade.set_window_layout(json.dumps({"layout": "compact", "height": 642})))
    assert ok["ok"] is True
    for bad in (None, "642", 12, 99999, True):
        payload = {"layout": "compact"} if bad is None else {"layout": "compact", "height": bad}
        assert json.loads(facade.set_window_layout(json.dumps(payload)))["ok"] is False
    assert facade.recorded_layouts == [("compact", 642)]


def test_dashboard_contract_v2_strategy_and_revision_metadata(qapp, tmp_path: Path):
    f = DashboardFacade(tmp_path)
    initial = json.loads(f.get_snapshot())
    assert initial["request_id"] is None
    assert initial["settings_revision"] == 0
    assert initial["snapshot_seq"] == 1
    assert initial["strategy"] == {
        "skills": ["jq", "pg"],
        "bonds": ["成长", "经济", "贪婪", "挑战"],
        "cards": [],
        "attributes": [],
        "merchant": {"enabled": True, "max_rerolls": 0, "gold_reserve": 0},
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
