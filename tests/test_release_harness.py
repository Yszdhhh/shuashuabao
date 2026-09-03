from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import tools.release_gate as release_gate
from tools.release_harness import _canonical_manifest_sha256, audit_bundle


def _make_bundle(tmp_path: Path, *, timeout_s: int = 10, source_sha: str = "a" * 40) -> tuple[Path, Path]:
    bundle = tmp_path / "ShuaBao"
    internal = bundle / "_internal"
    web_dist = internal / "web" / "dist"
    tls_dir = tmp_path / "python" / "DLLs"
    web_dist.mkdir(parents=True)
    tls_dir.mkdir(parents=True)

    exe = bundle / "ShuaBao.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"frozen-exe")
    for name, payload in (
        ("libssl-3-x64.dll", b"python-ssl"),
        ("libcrypto-3-x64.dll", b"python-crypto"),
    ):
        (tls_dir / name).write_bytes(payload)
        (internal / name).write_bytes(payload)
    (internal / "_ssl.pyd").write_bytes(b"python-ssl-extension")

    manifest = {"schema_version": 1, "source_sha": source_sha, "release_channel": "dev", "files": []}
    (bundle / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (bundle / "subscription_runtime.json").write_text(
        json.dumps({
            "schema_version": 1,
            "base_url": "https://subscription.example",
            "mode": "enforce",
            "release_channel": "dev",
            "timeout_s": timeout_s,
        }),
        encoding="utf-8",
    )
    (web_dist / "build_manifest.json").write_text(
        json.dumps({"schema_version": 1, "source_sha": source_sha, "source_tree_clean": True}),
        encoding="utf-8",
    )
    (bundle / "build_identity.json").write_text(
        json.dumps({
            "schema_version": 1,
            "source_sha": source_sha,
            "source_tree_clean": True,
            "exe_name": "ShuaBao.exe",
            "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
            "release_manifest_sha256": _canonical_manifest_sha256(manifest),
        }),
        encoding="utf-8",
    )
    return bundle, tls_dir.parent


def test_release_harness_accepts_a_complete_frozen_bundle(tmp_path: Path) -> None:
    bundle, python_root = _make_bundle(tmp_path)
    report = audit_bundle(
        bundle,
        expected_source_sha="a" * 40,
        python_root=python_root,
        require_clean=True,
    )
    assert report["status"] == "PASS", report["errors"]


def test_release_harness_allows_the_separate_ocr_runtime_root(tmp_path: Path) -> None:
    bundle, python_root = _make_bundle(tmp_path)
    vision_internal = bundle / "vision" / "_internal"
    vision_internal.mkdir(parents=True)
    for name in ("_ssl.pyd", "libssl-3-x64.dll", "libcrypto-3-x64.dll"):
        (vision_internal / name).write_bytes((bundle / "_internal" / name).read_bytes())

    report = audit_bundle(
        bundle,
        expected_source_sha="a" * 40,
        python_root=python_root,
        require_clean=True,
    )
    assert report["status"] == "PASS", report["errors"]


def test_release_harness_rejects_stale_identity_and_exe_hash(tmp_path: Path) -> None:
    bundle, python_root = _make_bundle(tmp_path)
    identity_path = bundle / "build_identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["source_sha"] = "b" * 40
    identity["exe_sha256"] = "0" * 64
    identity_path.write_text(json.dumps(identity), encoding="utf-8")

    report = audit_bundle(bundle, expected_source_sha="a" * 40, python_root=python_root)
    assert report["status"] == "FAIL"
    assert any("source_sha_matches" in error for error in report["errors"])
    assert any("frozen_exe_hash_matches" in error for error in report["errors"])


def test_release_harness_rejects_foreign_or_duplicate_tls_dlls(tmp_path: Path) -> None:
    bundle, python_root = _make_bundle(tmp_path)
    (bundle / "libcrypto-3-x64.dll").write_bytes(b"foreign-poppler-dll")
    (bundle / "_internal" / "libssl-3-x64.dll").write_bytes(b"foreign-python-dll")

    report = audit_bundle(bundle, expected_source_sha="a" * 40, python_root=python_root)
    assert report["status"] == "FAIL"
    assert any("libcrypto-3-x64.dll_unique" in error for error in report["errors"])
    assert any("libssl-3-x64.dll_matches_python" in error for error in report["errors"])


def test_release_harness_rejects_short_https_timeout_and_baked_secret_field(tmp_path: Path) -> None:
    bundle, python_root = _make_bundle(tmp_path, timeout_s=3)
    runtime_path = bundle / "subscription_runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["license_key"] = "must-not-be-packaged"
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")

    report = audit_bundle(bundle, expected_source_sha="a" * 40, python_root=python_root)
    assert report["status"] == "FAIL"
    assert any("subscription_runtime_no_secrets" in error for error in report["errors"])
    assert any("subscription_timeout_safe" in error for error in report["errors"])


def test_build_script_runs_harness_and_reads_shortcut_after_save() -> None:
    text = (Path(__file__).resolve().parents[1] / "build_release.ps1").read_text(encoding="utf-8")
    assert 'tools\\release_harness.py' in text
    assert '"--source-root", $PSScriptRoot' in text
    assert '"--bundle", $target' in text
    assert "$shortcutProof = $shell.CreateShortcut($lnk)" in text
    assert "$shortcutProof.TargetPath" in text
    assert "$shortcutProof.WorkingDirectory" in text


def test_release_gate_scrubs_live_subscription_environment(monkeypatch) -> None:
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_MODE", "enforce")
    monkeypatch.setenv("SHUABAO_SUBSCRIPTION_BASE_URL", "https://live.example")
    captured: dict[str, object] = {}

    def fake_run(_argv, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(release_gate.subprocess, "run", fake_run)
    release_gate._run(["python", "-V"])
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert "SHUABAO_SUBSCRIPTION_MODE" not in child_env
    assert "SHUABAO_SUBSCRIPTION_BASE_URL" not in child_env
    # The parent test process may still set an unrelated environment variable;
    # this check only proves the child gate environment is isolated.
    assert os.environ.get("SHUABAO_SUBSCRIPTION_MODE") == "enforce"
