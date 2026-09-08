"""Windows launcher smoke: Desktop .lnk → VBS → PS1 → current.json → app-*.

Does not start KK or send input. The frozen ShuaBao.exe is replaced with a
tiny asInvoker PE that only writes a marker file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shuabao.versioned_install import (
    install_release,
    read_current,
    rollback_release,
    write_current,
    write_launcher,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher smoke")

CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
SMOKE_CS = r"""
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Principal;
using System.Text;
class Smoke {
  static void Main() {
    bool admin = false;
    try {
      admin = new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator);
    } catch {}
    string cwd = Directory.GetCurrentDirectory();
    string exe = Assembly.GetExecutingAssembly().Location;
    string payload = "{\"cwd\":" + Q(cwd) + ",\"exe\":" + Q(exe)
      + ",\"admin\":" + (admin ? "true" : "false")
      + ",\"pid\":" + Process.GetCurrentProcess().Id + "}";
    var utf8 = new UTF8Encoding(false);
    File.WriteAllText(Path.Combine(cwd, "launched.json"), payload, utf8);
    string exeDir = Path.GetDirectoryName(exe);
    if (!string.IsNullOrEmpty(exeDir)) {
      File.WriteAllText(Path.Combine(exeDir, "launched.exe.json"), payload, utf8);
    }
    File.WriteAllText(Path.Combine(Path.GetTempPath(), "shuabao-p0-launch.json"), payload, utf8);
  }
  static string Q(string s) {
    return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
  }
}
"""


def _compile_smoke_exe(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    cs = dest.with_suffix(".cs")
    cs.write_text(SMOKE_CS, encoding="utf-8")
    assert CSC.is_file(), f"csc.exe missing: {CSC}"
    compiled = subprocess.run(
        [str(CSC), "/nologo", "/target:exe", f"/out:{dest}", str(cs)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    assert dest.is_file()
    return dest


def _kill_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )


def _wait_marker(path: Path, timeout_s: float = 12.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
                continue
        time.sleep(0.1)
    raise AssertionError(f"launcher did not write marker: {path}")


def _run_vbs(vbs: Path, timeout_s: float) -> int:
    proc = subprocess.Popen(
        ["wscript.exe", "//nologo", str(vbs)],
        cwd=str(vbs.parent),
    )
    try:
        return int(proc.wait(timeout=timeout_s))
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        return -1


def _host_probe() -> dict[str, str]:
    ps = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Write-Output ('CurrentUser=' + (Get-ExecutionPolicy -Scope CurrentUser)); "
            "Write-Output ('Process=' + (Get-ExecutionPolicy -Scope Process)); "
            "Write-Output ('LocalMachine=' + (Get-ExecutionPolicy -Scope LocalMachine))",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    wsh = subprocess.run(
        [
            "reg",
            "query",
            r"HKLM\SOFTWARE\Microsoft\Windows Script Host\Settings",
            "/v",
            "Enabled",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    return {
        "execution_policy": (ps.stdout or "").strip(),
        "execution_policy_err": (ps.stderr or "").strip(),
        "wsh_reg": ((wsh.stdout or "") + (wsh.stderr or "")).strip(),
        "wscript": str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe"),
    }


def _load_harness_helpers():
    import importlib.util

    path = Path(__file__).with_name("test_release_harness.py")
    spec = importlib.util.spec_from_file_location("test_release_harness_helpers_smoke", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _swap_exe(app_dir: Path, pe: Path) -> bytes:
    target = app_dir / "ShuaBao.exe"
    original = target.read_bytes()
    target.write_bytes(pe.read_bytes())
    return original


def test_windows_launcher_shortcut_vbs_ps1_current_and_rollback(tmp_path: Path, monkeypatch) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from shuabao import release_signing

    private = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        release_signing,
        "PINNED_MANIFEST_PUBLIC_KEYS",
        {"test-manifest": private.public_key()},
    )
    helpers = _load_harness_helpers()
    root = tmp_path / "刷刷宝安装根"
    n_bundle, _ = helpers._make_bundle(tmp_path / "n", private, source_sha="a" * 40)
    n1_bundle, _ = helpers._make_bundle(tmp_path / "n1", private, source_sha="b" * 40)
    install_release(n_bundle, root)
    install_release(n1_bundle, root)

    pe = _compile_smoke_exe(tmp_path / "smoke-pe" / "ShuaBao.exe")
    n_dir = root / "app-0.3-dev-aaaaaaaaaaaa"
    n1_dir = root / "app-0.3-dev-bbbbbbbbbbbb"
    launcher_vbs = write_launcher(root)
    ps1 = launcher_vbs.with_name("ShuaBaoLauncher.ps1")
    ps1_text = ps1.read_text(encoding="utf-8")
    vbs_text = launcher_vbs.read_text(encoding="utf-8")
    assert "Start-Process" in ps1_text
    assert "-Verb" not in ps1_text
    assert "runas" not in ps1_text.lower()
    assert "ExecutionPolicy Bypass" in vbs_text

    spec = (Path(__file__).resolve().parents[1] / "ShuaBao.spec").read_text(encoding="utf-8")
    assert "uac_admin=True" in spec

    probe = _host_probe()
    assert not probe["execution_policy"] or any(
        p in probe["execution_policy"] for p in ("RemoteSigned", "Bypass", "Unrestricted")
    )
    # Missing Enabled value means WSH is at the OS default (enabled).
    assert "0x0" not in probe["wsh_reg"]
    # Physical-desktop capability probe: must be equivalent to the real
    # operations below — Unicode (Chinese) .lnk filename on the real
    # Desktop, VBS TargetPath, WorkingDirectory, and Save() persistence.
    # GitHub hosted runners fail here (WScript.Shell Save() raises
    # FileNotFoundException for non-ASCII lnk names), so skip the
    # physical-desktop segment only when this exact capability is absent.
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    com_probe_lnk = desktop / "刷刷宝-P0-probe.lnk"
    com_ok = False
    try:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
                "$s.TargetPath = $env:VBS;"
                "$s.Arguments = '';"
                "$s.WorkingDirectory = $env:WD;"
                "$s.Save()",
            ],
            check=True,
            timeout=20,
            env={
                **os.environ,
                "LNK": str(com_probe_lnk),
                "VBS": str(launcher_vbs),
                "WD": str(launcher_vbs.parent),
            },
        )
        # Save() returning without error is not proof — read back what persisted.
        proof = tmp_path / "com-probe-proof.txt"
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
                "$utf8 = New-Object System.Text.UTF8Encoding $false;"
                "[IO.File]::WriteAllText($env:PROOF, ($s.TargetPath + [char]10 + $s.WorkingDirectory), $utf8)",
            ],
            check=True,
            timeout=20,
            env={**os.environ, "LNK": str(com_probe_lnk), "PROOF": str(proof)},
        )
        lines = proof.read_text(encoding="utf-8").splitlines()
        target = lines[0] if lines else ""
        workdir = lines[1] if len(lines) > 1 else ""
        com_ok = (
            Path(target).resolve() == launcher_vbs.resolve()
            and Path(workdir).resolve() == launcher_vbs.parent.resolve()
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError):
        com_ok = False
    finally:
        com_probe_lnk.unlink(missing_ok=True)
    if not com_ok:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.skip(
                "WScript.Shell cannot persist Unicode .lnk with VBS target on this host (CI_ENVIRONMENT_NOT_CAPABLE)"
            )
        pytest.fail(
            "LOCAL_WINDOWS_SHORTCUT_GT_FAILED: WScript.Shell cannot persist Unicode .lnk with VBS target on local Windows host"
        )

    lnk = desktop / "刷刷宝-P0-smoke.lnk"

    def _create_shortcut() -> None:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
                "$s.TargetPath = $env:VBS;"
                "$s.Arguments = '';"
                "$s.WorkingDirectory = $env:WD;"
                "$s.Save()",
            ],
            check=True,
            timeout=20,
            env={
                **os.environ,
                "LNK": str(lnk),
                "VBS": str(launcher_vbs),
                "WD": str(launcher_vbs.parent),
            },
        )

    def _read_shortcut() -> tuple[str, str, str]:
        proof = tmp_path / "shortcut-proof.txt"
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
                "$utf8 = New-Object System.Text.UTF8Encoding $false;"
                "[IO.File]::WriteAllText($env:PROOF, ($s.TargetPath + [char]10 + $s.WorkingDirectory + [char]10 + [string]$s.Arguments), $utf8)",
            ],
            check=True,
            timeout=20,
            env={**os.environ, "LNK": str(lnk), "PROOF": str(proof)},
        )
        lines = proof.read_text(encoding="utf-8").splitlines()
        target = lines[0] if lines else ""
        workdir = lines[1] if len(lines) > 1 else ""
        args = lines[2] if len(lines) > 2 else ""
        return target, workdir, args

    original_n1 = _swap_exe(n1_dir, pe)
    (n1_dir / "launched.json").unlink(missing_ok=True)
    try:
        _create_shortcut()
        target, workdir, args = _read_shortcut()
        assert Path(target).resolve() == launcher_vbs.resolve(), target
        assert Path(workdir).resolve() == launcher_vbs.parent.resolve(), workdir
        assert args == ""

        # The Desktop .lnk target is the VBS; invoking wscript is the same
        # process Windows uses for a .vbs shortcut (no KK / no SendInput).
        direct = subprocess.run(
            [str(n1_dir / "ShuaBao.exe")],
            cwd=str(n1_dir),
            timeout=8,
            check=False,
        )
        assert direct.returncode == 0, direct
        assert (n1_dir / "launched.json").is_file()
        (n1_dir / "launched.json").unlink()
        Path(os.environ.get("TEMP", "")).joinpath("shuabao-p0-launch.json").unlink(missing_ok=True)

        rc = _run_vbs(launcher_vbs, timeout_s=15)
        if rc != 0:
            pointer = json.loads((root / "current.json").read_text(encoding="utf-8"))
            identity = json.loads((n1_dir / "build_identity.json").read_text(encoding="utf-8"))
            raise AssertionError(
                "VBS launcher failed on the N+1 path "
                f"rc={rc} exe={ (n1_dir / 'ShuaBao.exe').is_file() } "
                f"size={(n1_dir / 'ShuaBao.exe').stat().st_size if (n1_dir / 'ShuaBao.exe').is_file() else 0} "
                f"current={pointer.get('current')!r} "
                f"ptr_sha={pointer.get('current_source_sha')!r} "
                f"id_sha={identity.get('source_sha')!r} "
                f"ptr_ch={pointer.get('current_release_channel')!r} "
                f"id_ch={identity.get('release_channel')!r} "
                f"ptr_man={pointer.get('current_release_manifest_sha256')!r} "
                f"id_man={identity.get('release_manifest_sha256')!r}"
            )
        try:
            marker = _wait_marker(n1_dir / "launched.json")
        except AssertionError:
            temp_marker = Path(os.environ["TEMP"]) / "shuabao-p0-launch.json"
            extra = temp_marker.read_text(encoding="utf-8") if temp_marker.is_file() else "no-temp-marker"
            exe_marker = n1_dir / "launched.exe.json"
            extra2 = exe_marker.read_text(encoding="utf-8") if exe_marker.is_file() else "no-exe-marker"
            raise AssertionError(f"no cwd marker; temp={extra}; exe={extra2}") from None
        assert Path(marker["cwd"]).resolve() == n1_dir.resolve()
        assert Path(marker["exe"]).resolve() == (n1_dir / "ShuaBao.exe").resolve()
        assert marker["admin"] is False
    finally:
        (n1_dir / "ShuaBao.exe").write_bytes(original_n1)
        if lnk.exists():
            lnk.unlink()

    pointer_before = read_current(root)
    assert pointer_before is not None
    assert pointer_before["current"] == "app-0.3-dev-bbbbbbbbbbbb"
    rolled = rollback_release(root)
    assert rolled["current"] == "app-0.3-dev-aaaaaaaaaaaa"
    original_n = _swap_exe(n_dir, pe)
    (n_dir / "launched.json").unlink(missing_ok=True)
    try:
        rc = _run_vbs(launcher_vbs, timeout_s=12)
        assert rc == 0
        marker = _wait_marker(n_dir / "launched.json")
        assert Path(marker["cwd"]).resolve() == n_dir.resolve()
        assert "aaaaaaaaaaaa" in marker["exe"]
        assert marker["admin"] is False
    finally:
        (n_dir / "ShuaBao.exe").write_bytes(original_n)

    (n_dir / "launched.json").unlink(missing_ok=True)
    (n1_dir / "launched.json").unlink(missing_ok=True)
    (n_dir / "launched.exe.json").unlink(missing_ok=True)
    (n1_dir / "launched.exe.json").unlink(missing_ok=True)
    bad_pointer = dict(pointer_before)
    bad_pointer["current"] = "not-an-app-dir"
    (root / "current.json").write_text(json.dumps(bad_pointer, indent=2), encoding="utf-8")
    rc_invalid = _run_vbs(launcher_vbs, timeout_s=6)
    assert rc_invalid != 0
    assert not (n_dir / "launched.json").exists()
    assert not (n1_dir / "launched.json").exists()

    identity = json.loads((n_dir / "build_identity.json").read_text(encoding="utf-8"))
    write_current(root, identity, "app-0.3-dev-aaaaaaaaaaaa", "app-0.3-dev-bbbbbbbbbbbb")
    missing = n_dir / "ShuaBao.exe"
    saved = missing.read_bytes()
    missing.unlink()
    try:
        rc_missing = _run_vbs(launcher_vbs, timeout_s=6)
        assert rc_missing != 0
        assert not (n_dir / "launched.json").exists()
    finally:
        missing.write_bytes(saved)
