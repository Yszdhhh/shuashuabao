#!/usr/bin/env python3
"""Final frozen-package handoff checks.

This is deliberately a small, zero-input harness.  Source tests and a frozen
package are different artifacts; this command verifies the latter before a
desktop shortcut is handed to an operator.  It never opens the game, sends
input, contacts the subscription service, or reads a license key.

Typical use (the build script invokes the same check automatically)::

    python tools/release_harness.py --source-root . \
        --bundle C:/Users/10639/Desktop/ShuaBao --require-clean

The check catches the incidents that previously survived source-only tests:
stale desktop copies, stale Web UI, mismatched ``_ssl.pyd``/OpenSSL DLLs, and
short tunnel timeouts.  A non-zero exit code is a hard stop for packaging.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


APP_EXE = "ShuaBao.exe"
TLS_DLL_NAMES = ("libssl-3-x64.dll", "libcrypto-3-x64.dll")
RUNTIME_KEYS = frozenset(
    {"schema_version", "base_url", "mode", "release_channel", "timeout_s"}
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _canonical_manifest_sha256(manifest: dict[str, object]) -> str:
    payload = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git(source_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _is_loopback(host: str) -> bool:
    normalized = host.rstrip(".").lower().strip("[]")
    if normalized == "localhost":
        return True
    if normalized == "127.0.0.1" or normalized.startswith("127."):
        return True
    return normalized == "::1"


def _files_named(root: Path, name: str) -> list[Path]:
    wanted = name.lower()
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.name.lower() == wanted),
        key=lambda path: path.as_posix().lower(),
    )


def _frozen_runtime_roots(bundle: Path) -> list[Path]:
    """Return the onedir roots that own a Python extension runtime.

    The desktop package contains the dashboard interpreter under ``_internal``
    and the isolated OCR worker under ``vision/_internal``.  Two copies are
    therefore expected, but a duplicate inside either runtime (or a DLL at an
    unrelated location) is still a load-order hazard.
    """

    roots = [
        candidate
        for candidate in (bundle / "_internal", bundle / "vision" / "_internal")
        if candidate.is_dir()
    ]
    return roots or [bundle]


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _python_tls_path(python_root: Path, name: str) -> Path:
    # Accept either a Python base prefix or its DLLs directory.  This keeps the
    # CLI useful with a venv and makes the unit tests independent of Windows.
    return python_root / name if python_root.name.lower() == "dlls" else python_root / "DLLs" / name


def audit_bundle(
    bundle_root: Path,
    *,
    source_root: Path | None = None,
    python_root: Path | None = None,
    expected_source_sha: str | None = None,
    require_clean: bool = False,
) -> dict[str, object]:
    """Return a machine-readable package audit without performing any input."""

    bundle = bundle_root.resolve()
    source = source_root.resolve() if source_root is not None else None
    checks: dict[str, dict[str, object]] = {}
    errors: list[str] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            errors.append(f"{name}: {detail}")

    check("bundle_directory", bundle.is_dir(), str(bundle))

    source_sha = expected_source_sha or (_git(source, "rev-parse", "HEAD") if source else "")
    if source is not None and require_clean:
        dirty = _git(source, "status", "--porcelain", "--untracked-files=no")
        check("source_tree_clean", not dirty, "clean" if not dirty else dirty)

    identity_path = bundle / "build_identity.json"
    identity = _read_json(identity_path)
    check("build_identity_present", identity is not None, str(identity_path))
    if identity is None:
        identity = {}

    identity_sha = str(identity.get("source_sha") or "")
    if source_sha:
        check("source_sha_matches", identity_sha == source_sha, f"identity={identity_sha or '<missing>'} expected={source_sha}")
    else:
        check("source_sha_available", False, "cannot resolve source git HEAD")
    check("identity_tree_clean", not require_clean or identity.get("source_tree_clean") is True, str(identity.get("source_tree_clean")))

    exe_name = str(identity.get("exe_name") or APP_EXE)
    exe_path = bundle / exe_name
    exe_exists = exe_path.is_file() and exe_name == APP_EXE
    check("frozen_exe_present", exe_exists, str(exe_path))
    if exe_exists:
        actual_exe_sha = sha256_file(exe_path)
        expected_exe_sha = str(identity.get("exe_sha256") or "").lower()
        check("frozen_exe_hash_matches", bool(expected_exe_sha) and actual_exe_sha == expected_exe_sha, f"actual={actual_exe_sha} identity={expected_exe_sha or '<missing>'}")

    manifest_path = bundle / "release_manifest.json"
    manifest = _read_json(manifest_path)
    check("release_manifest_present", manifest is not None, str(manifest_path))
    if manifest is None:
        manifest = {}
    check("release_manifest_schema", manifest.get("schema_version") == 1, str(manifest.get("schema_version")))
    if manifest:
        check("manifest_source_sha_matches", not source_sha or manifest.get("source_sha") == source_sha, str(manifest.get("source_sha")))
        expected_manifest_sha = str(identity.get("release_manifest_sha256") or "").lower()
        actual_manifest_sha = _canonical_manifest_sha256(manifest)
        check("manifest_hash_matches", bool(expected_manifest_sha) and actual_manifest_sha == expected_manifest_sha, f"actual={actual_manifest_sha} identity={expected_manifest_sha or '<missing>'}")

    # The Web shell has its own source handshake.  Requiring it here prevents a
    # freshly built Python EXE from being paired with an older ui-v2/dist.
    web_manifests = [
        path
        for path in _files_named(bundle, "build_manifest.json")
        if path.parent.name.lower() == "dist" and path.parent.parent.name.lower() == "web"
    ]
    check("web_build_manifest_present", len(web_manifests) == 1, ", ".join(str(path) for path in web_manifests) or "missing")
    if len(web_manifests) == 1:
        web_manifest = _read_json(web_manifests[0]) or {}
        check("web_source_sha_matches", not source_sha or web_manifest.get("source_sha") == source_sha, str(web_manifest.get("source_sha")))
        check("web_tree_clean", not require_clean or web_manifest.get("source_tree_clean") is True, str(web_manifest.get("source_tree_clean")))

    runtime_path = bundle / "subscription_runtime.json"
    runtime = _read_json(runtime_path)
    check("subscription_runtime_present", runtime is not None, str(runtime_path))
    if runtime is None:
        runtime = {}
    unknown_runtime_keys = sorted(set(runtime) - RUNTIME_KEYS)
    check("subscription_runtime_no_secrets", not unknown_runtime_keys, "unknown fields: " + ", ".join(unknown_runtime_keys) if unknown_runtime_keys else "no secret fields")
    base_url = str(runtime.get("base_url") or "")
    try:
        parsed = urlsplit(base_url)
        parsed_hostname = parsed.hostname
        parsed_scheme = parsed.scheme
        parsed_username = parsed.username
        parsed_password = parsed.password
    except ValueError:
        parsed = None
        parsed_hostname = parsed_scheme = parsed_username = parsed_password = None
    valid_url = bool(parsed_scheme in {"http", "https"} and parsed_hostname and not parsed_username and not parsed_password)
    if parsed_scheme == "http" and parsed_hostname and not _is_loopback(parsed_hostname):
        valid_url = False
    check("subscription_endpoint_safe", valid_url, base_url or "missing")
    try:
        timeout_s = float(runtime.get("timeout_s"))
    except (TypeError, ValueError):
        timeout_s = 0.0
    timeout_ok = timeout_s > 0 and (parsed_scheme != "https" or timeout_s >= 10.0)
    check("subscription_timeout_safe", timeout_ok, f"{timeout_s:g}s (HTTPS tunnel requires >=10s)")

    # PyInstaller's onedir package must contain exactly one TLS pair and it must
    # be the pair belonging to the Python interpreter that owns _ssl.pyd.  A
    # second same-named DLL is a load-order hazard (the incident that produced
    # the misleading ASN1/SSLError dialog).
    runtime_roots = _frozen_runtime_roots(bundle)
    package_tls: dict[str, list[Path]] = {name: _files_named(bundle, name) for name in TLS_DLL_NAMES}
    for name, paths in package_tls.items():
        outside = [path for path in paths if not any(_is_under(path, root) for root in runtime_roots)]
        per_root = [
            (root, [path for path in paths if _is_under(path, root)])
            for root in runtime_roots
        ]
        unique_ok = not outside and all(len(root_paths) == 1 for _, root_paths in per_root)
        detail = "; ".join(
            f"{root.relative_to(bundle)}={','.join(str(path.relative_to(bundle)) for path in root_paths) or 'missing'}"
            for root, root_paths in per_root
        )
        if outside:
            detail += "; outside=" + ",".join(str(path.relative_to(bundle)) for path in outside)
        check(f"{name}_unique", unique_ok, detail or "missing")
    ssl_extensions = _files_named(bundle, "_ssl.pyd")
    ssl_outside = [path for path in ssl_extensions if not any(_is_under(path, root) for root in runtime_roots)]
    ssl_per_root = [
        (root, [path for path in ssl_extensions if _is_under(path, root)])
        for root in runtime_roots
    ]
    ssl_unique = not ssl_outside and all(len(root_paths) == 1 for _, root_paths in ssl_per_root)
    ssl_detail = "; ".join(
        f"{root.relative_to(bundle)}={','.join(str(path.relative_to(bundle)) for path in root_paths) or 'missing'}"
        for root, root_paths in ssl_per_root
    )
    if ssl_outside:
        ssl_detail += "; outside=" + ",".join(str(path.relative_to(bundle)) for path in ssl_outside)
    check("python_ssl_extension_present", ssl_unique, ssl_detail or "missing")
    if python_root is not None:
        for name, paths in package_tls.items():
            source_dll = _python_tls_path(python_root, name)
            source_hash = sha256_file(source_dll) if source_dll.is_file() else ""
            runtime_hashes = []
            for root in runtime_roots:
                root_paths = [path for path in paths if _is_under(path, root)]
                if len(root_paths) == 1:
                    runtime_hashes.append((root, sha256_file(root_paths[0])))
            matches = bool(source_hash) and bool(runtime_hashes) and all(value == source_hash for _, value in runtime_hashes)
            detail = "; ".join(
                f"{root.relative_to(bundle)}={value}" for root, value in runtime_hashes
            ) or "package=<missing>"
            detail += f"; python={source_hash or '<missing>'}"
            check(f"{name}_matches_python", matches, detail)

    return {
        "status": "PASS" if not errors else "FAIL",
        "bundle": str(bundle),
        "source_sha": source_sha,
        "checks": checks,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="冻结 onedir 包目录")
    parser.add_argument("--source-root", type=Path, default=None, help="源码仓库根目录")
    parser.add_argument("--python-root", type=Path, default=None, help="构建 Python base prefix 或 DLLs 目录")
    parser.add_argument("--expected-source-sha", default="", help="测试/外部调用时显式提供源码 SHA")
    parser.add_argument("--require-clean", action="store_true", help="要求 tracked 工作树和 Web 构建清单均为 clean")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args(argv)

    report = audit_bundle(
        args.bundle,
        source_root=args.source_root,
        python_root=args.python_root,
        expected_source_sha=args.expected_source_sha or None,
        require_clean=args.require_clean,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for name, result in report["checks"].items():
            mark = "PASS" if result["ok"] else "FAIL"
            print(f"[release-harness] {mark} {name}: {result['detail']}")
        print(f"[release-harness] {report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
