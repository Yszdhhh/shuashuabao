"""Versioned install, current pointer, rollback, and stable launcher."""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from shuabao import versioned_install
from shuabao.versioned_install import (
    InstallError,
    LaunchError,
    install_release,
    launch_current,
    place_release,
    promote_release,
    read_current,
    resolve_launch_target,
    rollback_release,
    write_current,
)
from tools.release_harness import audit_bundle


def _load_harness_helpers():
    path = Path(__file__).with_name("test_release_harness.py")
    spec = importlib.util.spec_from_file_location("test_release_harness_helpers", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HARNESS = _load_harness_helpers()
_make_bundle = _HARNESS._make_bundle


@pytest.fixture
def signing_key(monkeypatch):
    private = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        "shuabao.release_signing.PINNED_MANIFEST_PUBLIC_KEYS",
        {"test-manifest": private.public_key()},
    )
    return private


def _bundle(tmp_path: Path, signing_key, source_sha: str, channel: str = "dev") -> tuple[Path, Path]:
    return _make_bundle(tmp_path, signing_key, source_sha=source_sha, channel=channel)


def test_fresh_install_writes_version_dir_and_current_pointer(tmp_path: Path, signing_key) -> None:
    bundle, python_root = _bundle(tmp_path / "b1", signing_key, "a" * 40)
    root = tmp_path / "install"
    root.mkdir()
    (root / "user_settings.json").write_text('{"keep": true}', encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "ShuaBao.log").write_text("old-log\n", encoding="utf-8")
    (root / "incidents").mkdir()
    (root / "incidents" / "keep.txt").write_text("incident\n", encoding="utf-8")

    result = install_release(bundle, root)
    pointer = read_current(root)
    assert result["switched"] is True
    assert pointer is not None
    assert pointer["current"] == "app-0.3-dev-aaaaaaaaaaaa"
    assert pointer["previous"] is None
    assert pointer["current_source_sha"] == "a" * 40
    assert pointer["current_release_channel"] == "dev"
    assert (root / pointer["current"] / "ShuaBao.exe").is_file()
    assert (root / "launcher" / "ShuaBaoLauncher.vbs").is_file()
    assert (root / "launcher" / "ShuaBaoLauncher.ps1").is_file()
    assert json.loads((root / "user_settings.json").read_text(encoding="utf-8")) == {"keep": True}
    assert (root / "logs" / "ShuaBao.log").read_text(encoding="utf-8") == "old-log\n"
    assert (root / "incidents" / "keep.txt").read_text(encoding="utf-8") == "incident\n"
    report = audit_bundle(
        Path(result["path"]),
        expected_source_sha="a" * 40,
        python_root=python_root,
        require_clean=True,
    )
    assert report["status"] == "PASS", report["errors"]
    assert launch_current(root, dry_run=True) == root / pointer["current"] / "ShuaBao.exe"


def test_n_to_n_plus_one_switches_current_and_keeps_previous(tmp_path: Path, signing_key) -> None:
    first, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    second, python_root = _bundle(tmp_path / "n1", signing_key, "b" * 40)
    root = tmp_path / "install"
    install_release(first, root)
    result = install_release(second, root)
    pointer = read_current(root)
    assert pointer is not None
    assert pointer["current"] == "app-0.3-dev-bbbbbbbbbbbb"
    assert pointer["previous"] == "app-0.3-dev-aaaaaaaaaaaa"
    assert (root / pointer["previous"] / "ShuaBao.exe").is_file()
    assert (root / pointer["current"] / "ShuaBao.exe").is_file()
    report = audit_bundle(
        Path(result["path"]),
        expected_source_sha="b" * 40,
        python_root=python_root,
        require_clean=True,
    )
    assert report["status"] == "PASS", report["errors"]


def test_place_copies_to_staging_validates_then_renames() -> None:
    """Failed-install atomicity contract: dest is created only after staging verify."""
    src = inspect.getsource(versioned_install.place_release)
    assert src.index("_copy_bundle(src, staging)") < src.index("verify_release_dir(staging)")
    assert src.index("verify_release_dir(staging)") < src.index("os.rename(staging, dest)")
    except_block = src[src.index("except Exception:"):]
    assert "_rmtree(staging)" in except_block


def test_copy_failure_leaves_no_final_dir_and_can_retry(tmp_path: Path, signing_key, monkeypatch) -> None:
    bundle, _ = _bundle(tmp_path / "b", signing_key, "a" * 40)
    root = tmp_path / "install"
    dest = root / "app-0.3-dev-aaaaaaaaaaaa"

    def boom(src, dst, *args, **kwargs):
        Path(dst).mkdir(parents=True)
        (Path(dst) / "partial.bin").write_bytes(b"incomplete")
        raise OSError("simulated copy failure")

    original = versioned_install.shutil.copytree
    monkeypatch.setattr(versioned_install.shutil, "copytree", boom)
    with pytest.raises(OSError, match="simulated copy failure"):
        place_release(bundle, root)
    assert not dest.exists()
    assert not list(root.glob("*.staging"))
    monkeypatch.setattr(versioned_install.shutil, "copytree", original)
    result = place_release(bundle, root)
    assert result["copied"] is True
    assert dest.is_dir()
    assert (dest / "ShuaBao.exe").is_file()


def test_staging_validation_failure_leaves_no_final_dir_and_can_retry(
    tmp_path: Path, signing_key, monkeypatch
) -> None:
    bundle, _ = _bundle(tmp_path / "b", signing_key, "a" * 40)
    root = tmp_path / "install"
    dest = root / "app-0.3-dev-aaaaaaaaaaaa"
    real_verify = versioned_install.verify_release_dir

    def wrapped(path, *args, **kwargs):
        identity = real_verify(path, *args, **kwargs)
        if Path(path).name.endswith(".staging"):
            raise InstallError("simulated staging validation failure")
        return identity

    monkeypatch.setattr(versioned_install, "verify_release_dir", wrapped)
    with pytest.raises(InstallError, match="staging validation"):
        place_release(bundle, root)
    assert not dest.exists()
    assert not list(root.glob("*.staging"))
    monkeypatch.setattr(versioned_install, "verify_release_dir", real_verify)
    result = place_release(bundle, root)
    assert dest.is_dir()
    assert result["dir_name"] == dest.name


def test_rename_failure_leaves_no_final_dir_and_can_retry(tmp_path: Path, signing_key, monkeypatch) -> None:
    bundle, _ = _bundle(tmp_path / "b", signing_key, "a" * 40)
    root = tmp_path / "install"
    dest = root / "app-0.3-dev-aaaaaaaaaaaa"
    real_rename = versioned_install.os.rename

    def boom(src, dst):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(versioned_install.os, "rename", boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        place_release(bundle, root)
    assert not dest.exists()
    assert not list(root.glob("*.staging"))
    monkeypatch.setattr(versioned_install.os, "rename", real_rename)
    result = place_release(bundle, root)
    assert dest.is_dir()
    assert result["copied"] is True


def test_failed_new_install_does_not_switch_current(tmp_path: Path, signing_key) -> None:
    good, _ = _bundle(tmp_path / "good", signing_key, "a" * 40)
    bad, _ = _bundle(tmp_path / "bad", signing_key, "c" * 40)
    (bad / "ShuaBao.exe").unlink()
    root = tmp_path / "install"
    install_release(good, root)
    before = read_current(root)
    with pytest.raises(InstallError):
        install_release(bad, root)
    after = read_current(root)
    assert after == before
    assert after is not None
    assert after["current"] == "app-0.3-dev-aaaaaaaaaaaa"
    assert not (root / "app-0.3-dev-cccccccccccc").exists()
    assert not list(root.glob("*.staging"))


def test_promote_and_rollback_write_launcher_before_current_pointer() -> None:
    for fn in (versioned_install.promote_release, versioned_install.rollback_release):
        src = inspect.getsource(fn)
        assert src.index("write_launcher(") < src.index("write_current("), fn.__name__


def test_promote_keeps_current_when_write_launcher_fails(tmp_path: Path, signing_key, monkeypatch) -> None:
    first, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    second, _ = _bundle(tmp_path / "n1", signing_key, "b" * 40)
    root = tmp_path / "install"
    install_release(first, root)
    placed = place_release(second, root)
    before = read_current(root)

    def boom(*args, **kwargs):
        raise InstallError("simulated launcher write failure")

    monkeypatch.setattr(versioned_install, "write_launcher", boom)
    with pytest.raises(InstallError, match="launcher write failure"):
        promote_release(root, placed["dir_name"])
    assert read_current(root) == before
    assert before is not None
    assert before["current"] == "app-0.3-dev-aaaaaaaaaaaa"


def test_rollback_keeps_current_when_write_launcher_fails(tmp_path: Path, signing_key, monkeypatch) -> None:
    first, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    second, _ = _bundle(tmp_path / "n1", signing_key, "b" * 40)
    root = tmp_path / "install"
    install_release(first, root)
    install_release(second, root)
    before = read_current(root)

    def boom(*args, **kwargs):
        raise InstallError("simulated launcher write failure")

    monkeypatch.setattr(versioned_install, "write_launcher", boom)
    with pytest.raises(InstallError, match="launcher write failure"):
        rollback_release(root)
    assert read_current(root) == before
    assert before is not None
    assert before["current"] == "app-0.3-dev-bbbbbbbbbbbb"


def test_place_without_switch_then_promote_switches_current(tmp_path: Path, signing_key) -> None:
    first, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    second, _ = _bundle(tmp_path / "n1", signing_key, "b" * 40)
    root = tmp_path / "install"
    install_release(first, root)
    placed = place_release(second, root)
    assert placed["dir_name"] == "app-0.3-dev-bbbbbbbbbbbb"
    pointer = read_current(root)
    assert pointer is not None
    assert pointer["current"] == "app-0.3-dev-aaaaaaaaaaaa"
    assert (root / placed["dir_name"] / "ShuaBao.exe").is_file()
    promote_release(root, placed["dir_name"])
    pointer = read_current(root)
    assert pointer is not None
    assert pointer["current"] == "app-0.3-dev-bbbbbbbbbbbb"
    assert pointer["previous"] == "app-0.3-dev-aaaaaaaaaaaa"


def test_existing_dir_with_different_identity_is_not_overwritten(tmp_path: Path, signing_key) -> None:
    bundle, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    root = tmp_path / "install"
    dest = root / "app-0.3-dev-aaaaaaaaaaaa"
    dest.mkdir(parents=True)
    (dest / "ShuaBao.exe").write_bytes(b"not-the-release")
    (dest / "build_identity.json").write_text(
        json.dumps({
            "schema_version": 1,
            "source_sha": "a" * 40,
            "version": "0.3",
            "release_channel": "dev",
            "exe_name": "ShuaBao.exe",
            "exe_sha256": "0" * 64,
            "release_manifest_sha256": "1" * 64,
        }),
        encoding="utf-8",
    )
    with pytest.raises(InstallError, match="拒绝覆盖"):
        place_release(bundle, root)
    assert (dest / "ShuaBao.exe").read_bytes() == b"not-the-release"


def test_rollback_validates_previous_with_verify_release_dir() -> None:
    """Rollback reuses verify_release_dir (attested files on), not pointer-only trust."""
    src = inspect.getsource(versioned_install.rollback_release)
    target_line = [line for line in src.splitlines() if "verify_release_dir(dest)" in line][0]
    assert "check_file_hashes=False" not in target_line
    assert "identity = verify_release_dir(dest)" in src


def test_rollback_rejects_corrupt_attested_file_without_switching(tmp_path: Path, signing_key) -> None:
    first, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    second, _ = _bundle(tmp_path / "n1", signing_key, "b" * 40)
    root = tmp_path / "install"
    install_release(first, root)
    install_release(second, root)
    previous = root / "app-0.3-dev-aaaaaaaaaaaa"
    (previous / "subscription_runtime.json").write_text('{"tampered": true}', encoding="utf-8")
    before = read_current(root)
    with pytest.raises(InstallError, match="manifest 文件 hash 失败"):
        rollback_release(root)
    assert read_current(root) == before
    assert before is not None
    assert before["current"] == "app-0.3-dev-bbbbbbbbbbbb"


def test_rollback_rejects_source_channel_and_canonical_manifest_mismatch(
    tmp_path: Path, signing_key
) -> None:
    first, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    second, _ = _bundle(tmp_path / "n1", signing_key, "b" * 40)
    root = tmp_path / "install"
    install_release(first, root)
    install_release(second, root)
    previous = root / "app-0.3-dev-aaaaaaaaaaaa"
    before = read_current(root)

    identity_path = previous / "build_identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["source_sha"] = "e" * 40
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    with pytest.raises(InstallError, match="source_sha"):
        rollback_release(root)
    assert read_current(root) == before

    identity["source_sha"] = "a" * 40
    identity["release_channel"] = "release"
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    with pytest.raises(InstallError, match="release_channel"):
        rollback_release(root)
    assert read_current(root) == before

    identity["release_channel"] = "dev"
    identity["release_manifest_sha256"] = "f" * 64
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    with pytest.raises(InstallError, match="canonical SHA"):
        rollback_release(root)
    assert read_current(root) == before


def test_rollback_switches_to_previous_without_rebuild(tmp_path: Path, signing_key) -> None:
    first, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    second, _ = _bundle(tmp_path / "n1", signing_key, "b" * 40)
    root = tmp_path / "install"
    root.mkdir()
    (root / "user_settings.json").write_text('{"keep": 1}', encoding="utf-8")
    install_release(first, root)
    install_release(second, root)
    rolled = rollback_release(root)
    pointer = read_current(root)
    assert pointer is not None
    assert pointer["current"] == "app-0.3-dev-aaaaaaaaaaaa"
    assert pointer["previous"] == "app-0.3-dev-bbbbbbbbbbbb"
    assert rolled["rolled_back_from"] == "app-0.3-dev-bbbbbbbbbbbb"
    assert resolve_launch_target(root) == root / "app-0.3-dev-aaaaaaaaaaaa" / "ShuaBao.exe"
    assert json.loads((root / "user_settings.json").read_text(encoding="utf-8")) == {"keep": 1}


def test_third_install_prunes_n_minus_two(tmp_path: Path, signing_key) -> None:
    root = tmp_path / "install"
    install_release(_bundle(tmp_path / "n", signing_key, "a" * 40)[0], root)
    install_release(_bundle(tmp_path / "n1", signing_key, "b" * 40)[0], root)
    install_release(_bundle(tmp_path / "n2", signing_key, "c" * 40)[0], root)
    names = {p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("app-")}
    assert names == {"app-0.3-dev-bbbbbbbbbbbb", "app-0.3-dev-cccccccccccc"}
    pointer = read_current(root)
    assert pointer is not None
    assert pointer["current"] == "app-0.3-dev-cccccccccccc"
    assert pointer["previous"] == "app-0.3-dev-bbbbbbbbbbbb"


def test_launcher_rejects_missing_and_invalid_targets(tmp_path: Path, signing_key) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(LaunchError, match="current.json"):
        resolve_launch_target(root)

    first, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    install_release(first, root)
    pointer = read_current(root)
    assert pointer is not None
    dest = root / pointer["current"]
    exe = dest / "ShuaBao.exe"
    exe.unlink()
    with pytest.raises(LaunchError):
        resolve_launch_target(root)

    missing_root = tmp_path / "missing-exe-restored"
    install_release(first, missing_root)
    pointer = read_current(missing_root)
    assert pointer is not None
    write_current(
        missing_root,
        {
            "version": "0.3",
            "release_channel": "dev",
            "source_sha": "b" * 40,
            "release_manifest_sha256": "f" * 64,
        },
        pointer["current"],
        None,
    )
    with pytest.raises(LaunchError, match="source_sha"):
        resolve_launch_target(missing_root)


def test_cli_status_and_rollback(tmp_path: Path, signing_key, capsys) -> None:
    first, _ = _bundle(tmp_path / "n", signing_key, "a" * 40)
    second, _ = _bundle(tmp_path / "n1", signing_key, "b" * 40)
    root = tmp_path / "install"
    assert versioned_install.main(["install", "--bundle", str(first), "--install-root", str(root)]) == 0
    assert versioned_install.main(["install", "--bundle", str(second), "--install-root", str(root)]) == 0
    capsys.readouterr()
    assert versioned_install.main(["rollback", "--install-root", str(root)]) == 0
    capsys.readouterr()
    assert versioned_install.main(["launch", "--install-root", str(root), "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["exe"].endswith("ShuaBao.exe")
    assert "aaaaaaaaaaaa" in payload["exe"]


def test_launcher_templates_mention_identity_checks() -> None:
    root = Path(__file__).resolve().parents[1]
    ps1_path = root / "tools" / "launcher" / "ShuaBaoLauncher.ps1"
    vbs_path = root / "tools" / "launcher" / "ShuaBaoLauncher.vbs"
    assert ps1_path.read_bytes().startswith(b"\xef\xbb\xbf"), "Windows PowerShell 5.1 needs a UTF-8 BOM to parse Chinese strings"
    ps1 = ps1_path.read_text(encoding="utf-8-sig")
    vbs = vbs_path.read_text(encoding="ascii")
    assert "current.json" in ps1
    assert "build_identity.json" in ps1
    assert "Start-Process" in ps1
    assert "SHUABAO_SUBSCRIPTION" not in ps1
    assert "activate_device" not in ps1
    assert "ShuaBaoLauncher.ps1" in vbs
    assert "WindowStyle Hidden" in vbs
    assert "ExecutionPolicy Bypass" in vbs


def test_build_identity_metadata_exposes_version_and_channel(tmp_path: Path) -> None:
    from shuabao.shell.dashboard_facade import _build_identity_metadata

    identity = {
        "schema_version": 1,
        "version": "0.3",
        "release_channel": "dev",
        "source_sha": "a" * 40,
        "release_manifest_sha256": "b" * 64,
    }
    (tmp_path / "build_identity.json").write_text(json.dumps(identity), encoding="utf-8")
    metadata = _build_identity_metadata(tmp_path)
    assert metadata["version"] == "0.3"
    assert metadata["release_channel"] == "dev"
    assert metadata["source_sha"] == "a" * 40
