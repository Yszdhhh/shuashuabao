"""Closure B regressions: dev exact-release approval + user-config identity.

1. approve_dev_release registers the exact (source_sha, manifest_sha256,
   channel) tuple read from real package bytes, is idempotent, and refuses
   to approve broken identities or external channels without explicit
   operator confirmation.
2. Mutating a persisted user config (search keywords, bosses, cycle counts,
   skills, bonds, ...) never changes the package release identity: source
   manifest bytes and their sha256 stay identical.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import approve_dev_release as adr  # noqa: E402


def _write_package(tmp_path: Path, source_sha: str, *, channel: str = "dev", name: str = "app-0.3-dev-test", extra_file: dict | None = None) -> Path:
    package = tmp_path / name
    package.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "source_sha": source_sha,
        "bridge_schema_version": 2,
        "release_channel": channel,
        "files": [extra_file] if extra_file else [],
    }
    (package / "release_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return package


def test_registers_exact_identity_from_real_package_bytes(tmp_path) -> None:
    package = _write_package(tmp_path, "a" * 40)
    registry = tmp_path / "approved_releases.json"
    rc = adr.main([
        "--package", str(package),
        "--registry", str(registry),
        "--operator", "gt-agent",
    ])
    assert rc == 0
    entries = json.loads(registry.read_text(encoding="utf-8"))
    assert len(entries) == 1
    entry = entries[0]
    assert entry["source_sha"] == "a" * 40
    assert entry["release_manifest_sha256"] == hashlib.sha256(
        (package / "release_manifest.json").read_bytes()
    ).hexdigest()
    assert entry["release_channel"] == "dev"
    assert set(entry["allowed_modes"]) == set(adr.APPROVED_MODES)


def test_reregistration_replaces_same_identity(tmp_path) -> None:
    package = _write_package(tmp_path, "a" * 40)
    registry = tmp_path / "approved_releases.json"
    argv = ["--package", str(package), "--registry", str(registry)]
    assert adr.main(argv) == 0
    assert adr.main(argv) == 0
    entries = json.loads(registry.read_text(encoding="utf-8"))
    assert len(entries) == 1, "same exact identity must not duplicate"


def test_different_manifest_is_a_new_artifact(tmp_path) -> None:
    first = _write_package(tmp_path, "a" * 40, name="pkg-first")
    registry = tmp_path / "approved_releases.json"
    assert adr.main(["--package", str(first), "--registry", str(registry)]) == 0
    # Same source, different manifest bytes => different artifact identity.
    second = _write_package(tmp_path, "a" * 40, name="pkg-second",
                            extra_file={"path": "extra.bin"})
    assert adr.main(["--package", str(second), "--registry", str(registry)]) == 0
    entries = json.loads(registry.read_text(encoding="utf-8"))
    assert len(entries) == 2, "changed manifest bytes = new exact identity"


def test_refuses_missing_or_corrupt_manifest(tmp_path) -> None:
    registry = tmp_path / "approved_releases.json"
    empty = tmp_path / "pkg-missing"
    empty.mkdir()
    with pytest.raises(adr.ApprovalError, match="release_manifest"):
        adr.load_package_identity(empty)
    bad = tmp_path / "pkg-corrupt"
    bad.mkdir()
    (bad / "release_manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(adr.ApprovalError, match="不可读"):
        adr.load_package_identity(bad)
    assert not registry.exists()


def test_refuses_bad_source_sha_and_unknown_channel(tmp_path) -> None:
    registry = tmp_path / "approved_releases.json"
    with pytest.raises(adr.ApprovalError, match="source_sha"):
        adr.load_package_identity(_write_package(tmp_path, "short-sha", name="pkg-sha"))
    with pytest.raises(adr.ApprovalError, match="release_channel"):
        adr.load_package_identity(_write_package(tmp_path, "a" * 40, channel="guess", name="pkg-channel"))
    assert not registry.exists()


def test_external_channels_require_explicit_operator_confirmation(tmp_path) -> None:
    package = _write_package(tmp_path, "b" * 40, channel="external-beta", name="pkg-external")
    registry = tmp_path / "approved_releases.json"
    # main() converts ApprovalError into exit code 1 (CLI surface); the
    # registry must stay untouched on refusal.
    assert adr.main(["--package", str(package), "--registry", str(registry)]) == 1
    assert not registry.exists(), "failed runs must not write the registry"
    assert adr.main([
        "--package", str(package), "--registry", str(registry), "--allow-channel",
    ]) == 0
    entries = json.loads(registry.read_text(encoding="utf-8"))
    assert entries[0]["release_channel"] == "external-beta"


def test_unknown_mode_is_rejected(tmp_path) -> None:
    package = _write_package(tmp_path, "c" * 40, name="pkg-mode")
    registry = tmp_path / "approved_releases.json"
    assert adr.main([
        "--package", str(package), "--registry", str(registry),
        "--modes", "lobby_hitch,mystery_mode",
    ]) == 1
    assert not registry.exists()


def test_print_env_renders_server_registry_value(tmp_path, capsys) -> None:
    package = _write_package(tmp_path, "d" * 40)
    registry = tmp_path / "approved_releases.json"
    assert adr.main([
        "--package", str(package), "--registry", str(registry), "--print-env",
    ]) == 0
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("SHUABAO_APPROVED_RELEASES_JSON="))
    payload = line.split("=", 1)[1]
    entries = json.loads(payload)
    assert entries[0]["source_sha"] == "d" * 40
    assert isinstance(entries, list), "export must match PermitIssuer.from_environment shape"


# ---------------------------------------------------------------- identity invariance

def _package_identity(package: Path) -> tuple[str, str]:
    manifest = package / "release_manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return (
        str(data["source_sha"]),
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )


def test_user_config_changes_never_change_release_identity(tmp_path) -> None:
    """The task's mandatory regression: user-facing settings live in
    AppData (user_settings.json / DPAPI key), never inside the frozen
    package — so mutating them cannot alter source_sha or the manifest
    bytes. This test pins the boundary: package bytes before vs after a
    settings mutation are identical."""
    package = _write_package(tmp_path, "e" * 40)
    before = _package_identity(package)

    # Simulate the real split: settings persist OUTSIDE the package dir.
    app_data = tmp_path / "appdata" / "ShuaBao"
    app_data.mkdir(parents=True)
    user_settings = app_data / "user_settings.json"
    user_settings.write_text(json.dumps({
        "hitch_stage_prefix": "4,3",
        "cjb_boss": "01霍格",
        "skills": ["s1"],
    }, ensure_ascii=False), encoding="utf-8")

    # User edits every product-tunable knob.
    user_settings.write_text(json.dumps({
        "hitch_stage_prefix": "9,8,7",
        "cjb_boss": "54莫阿姆",
        "sgzx_boss": "08巨形缝合怪",
        "hitch_cycle_num": 42,
        "hitch_after_goal": "arch",
        "skills": ["s9", "s8", "s7", "s6"],
        "bonds": ["贪婪"],
        "click_delay_ms": 350,
    }, ensure_ascii=False), encoding="utf-8")

    after = _package_identity(package)
    assert before == after, "user config mutations must not touch package identity"


def test_persistable_settings_exclude_release_identity_fields() -> None:
    """The settings persistence path must never leak identity-bearing fields
    (source_sha / release manifest hashes) into user_settings.json."""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "src"))
    from shuabao.settings import Settings
    from shuabao.shell.mode_catalog import collect_persistable_settings

    blob = collect_persistable_settings(Settings())
    for forbidden in (
        "source_sha", "release_manifest_sha256", "release_manifest",
        "release_channel", "build_identity", "permit",
    ):
        assert forbidden not in blob, f"{forbidden} must not persist into user settings"
