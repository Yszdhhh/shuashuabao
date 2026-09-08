"""Versioned frozen-app install: app-* dirs, atomic current pointer, local rollback.

Launcher/install only. No subscription, FSM, updater, or remote control.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

APP_ID = "ShuaBao"
APP_EXE = "ShuaBao.exe"
CURRENT_NAME = "current.json"
LAUNCHER_DIRNAME = "launcher"
STAGING_SUFFIX = ".staging"
POINTER_SCHEMA = 1
CHANNELS = ("dev", "internal-pilot", "external-beta", "release")
DIR_NAME_RE = re.compile(
    r"^app-(?P<version>[0-9]+(?:\.[0-9]+)*)-"
    r"(?P<channel>dev|internal-pilot|external-beta|release)-"
    r"(?P<sha>[0-9a-f]{12})$"
)
METADATA_EXCEPTIONS = frozenset({
    "release_manifest.json",
    "release_manifest.json.sig",
    "build_identity.json",
})
class InstallError(Exception):
    """Versioned install or pointer switch failed; current must stay unchanged."""


class LaunchError(Exception):
    """Stable launcher rejected the current pointer or target identity."""


def default_install_root() -> Path:
    override = os.environ.get("SHUABAO_INSTALL_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return (Path(local) / APP_ID).resolve()
    return (Path.home() / ".local" / "share" / APP_ID).resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstallError(f"无法读取 JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InstallError(f"JSON 根必须是 object: {path}")
    return payload


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_identity(release_dir: Path) -> dict[str, Any]:
    identity = _read_json(release_dir / "build_identity.json")
    if identity.get("schema_version") != 1:
        raise InstallError(f"build_identity schema 不受支持: {release_dir}")
    source_sha = str(identity.get("source_sha") or "").strip().lower()
    channel = str(identity.get("release_channel") or "").strip()
    version = str(identity.get("version") or "").strip()
    exe_name = str(identity.get("exe_name") or APP_EXE).strip()
    exe_sha = str(identity.get("exe_sha256") or "").strip().lower()
    manifest_sha = str(identity.get("release_manifest_sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise InstallError(f"build_identity source_sha 非法: {release_dir}")
    if channel not in CHANNELS:
        raise InstallError(f"build_identity release_channel 非法: {channel}")
    if not version or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        raise InstallError(f"build_identity version 非法: {version!r}")
    if exe_name != APP_EXE:
        raise InstallError(f"exe_name 必须是 {APP_EXE}: {exe_name}")
    if not re.fullmatch(r"[0-9a-f]{64}", exe_sha):
        raise InstallError(f"build_identity exe_sha256 非法: {release_dir}")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha):
        raise InstallError(f"build_identity release_manifest_sha256 非法: {release_dir}")
    identity["source_sha"] = source_sha
    identity["release_channel"] = channel
    identity["version"] = version
    identity["exe_sha256"] = exe_sha
    identity["release_manifest_sha256"] = manifest_sha
    return identity


def release_dir_name(identity: Mapping[str, Any]) -> str:
    source_sha = str(identity["source_sha"]).lower()
    return f"app-{identity['version']}-{identity['release_channel']}-{source_sha[:12]}"


def _canonical_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    from shuabao.release_signing import canonical_manifest_sha256

    return canonical_manifest_sha256(manifest)


def verify_release_dir(release_dir: Path, *, check_file_hashes: bool = True) -> dict[str, Any]:
    root = Path(release_dir).resolve()
    if not root.is_dir():
        raise InstallError(f"发行目录不存在: {root}")
    exe = root / APP_EXE
    if not exe.is_file():
        raise InstallError(f"缺少 {APP_EXE}: {root}")
    identity = load_identity(root)
    actual_exe = _sha256_file(exe)
    if actual_exe != identity["exe_sha256"]:
        raise InstallError(f"EXE hash 与 build_identity 不一致: {root}")
    manifest_path = root / "release_manifest.json"
    if not manifest_path.is_file():
        raise InstallError(f"缺少 release_manifest.json: {root}")
    manifest = _read_json(manifest_path)
    actual_manifest = _canonical_manifest_sha256(manifest)
    if actual_manifest != identity["release_manifest_sha256"]:
        raise InstallError(f"manifest canonical SHA 与 build_identity 不一致: {root}")
    if str(manifest.get("source_sha") or "").strip().lower() != identity["source_sha"]:
        raise InstallError(f"manifest source_sha 与 build_identity 不一致: {root}")
    if str(manifest.get("release_channel") or "").strip() != identity["release_channel"]:
        raise InstallError(f"manifest release_channel 与 build_identity 不一致: {root}")
    if check_file_hashes:
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise InstallError(f"release_manifest.files 为空: {root}")
        for entry in files:
            if not isinstance(entry, dict):
                raise InstallError(f"manifest 文件条目非法: {root}")
            relative = str(entry.get("path") or "").replace("\\", "/").strip()
            expected = str(entry.get("sha256") or "").strip().lower()
            if not relative or ".." in Path(relative).parts or Path(relative).is_absolute():
                raise InstallError(f"manifest 路径非法: {relative}")
            if relative in METADATA_EXCEPTIONS:
                continue
            target = root.joinpath(*relative.split("/"))
            if not target.is_file():
                raise InstallError(f"manifest 文件缺失: {relative}")
            if _sha256_file(target) != expected:
                raise InstallError(f"manifest 文件 hash 失败: {relative}")
    expected_name = release_dir_name(identity)
    if DIR_NAME_RE.match(root.name) and root.name != expected_name:
        raise InstallError(f"目录名与 identity 不一致: {root.name} != {expected_name}")
    return identity


def read_current(install_root: Path) -> dict[str, Any] | None:
    path = Path(install_root) / CURRENT_NAME
    if not path.is_file():
        return None
    payload = _read_json(path)
    if payload.get("schema_version") != POINTER_SCHEMA:
        raise InstallError(f"current.json schema 不受支持: {path}")
    current = str(payload.get("current") or "").strip()
    if not DIR_NAME_RE.match(current):
        raise InstallError(f"current.json current 非法: {current!r}")
    previous = payload.get("previous")
    if previous in ("", None):
        payload["previous"] = None
    else:
        previous = str(previous).strip()
        if not DIR_NAME_RE.match(previous):
            raise InstallError(f"current.json previous 非法: {previous!r}")
        payload["previous"] = previous
    payload["current"] = current
    return payload


def _pointer_payload(identity: Mapping[str, Any], current: str, previous: str | None) -> dict[str, Any]:
    return {
        "schema_version": POINTER_SCHEMA,
        "current": current,
        "previous": previous,
        "updated_at_utc": _utc_now(),
        "current_version": str(identity["version"]),
        "current_release_channel": str(identity["release_channel"]),
        "current_source_sha": str(identity["source_sha"]),
        "current_release_manifest_sha256": str(identity["release_manifest_sha256"]),
    }


def write_current(install_root: Path, identity: Mapping[str, Any], current: str, previous: str | None) -> dict[str, Any]:
    payload = _pointer_payload(identity, current, previous)
    atomic_write_json(Path(install_root) / CURRENT_NAME, payload)
    return payload


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _launcher_templates() -> Path:
    return _repo_root() / "tools" / "launcher"


def write_launcher(install_root: Path) -> Path:
    templates = _launcher_templates()
    dest = Path(install_root) / LAUNCHER_DIRNAME
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in ("ShuaBaoLauncher.vbs", "ShuaBaoLauncher.ps1"):
        src = templates / name
        if not src.is_file():
            raise InstallError(f"缺少 launcher 模板: {src}")
        target = dest / name
        tmp = dest / (name + ".tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, target)
        copied += 1
    if copied != 2:
        raise InstallError("launcher 模板复制不完整")
    icon_src = _repo_root() / "assets" / "branding" / "app_logo.ico"
    if icon_src.is_file():
        icon_tmp = dest / "app_logo.ico.tmp"
        shutil.copy2(icon_src, icon_tmp)
        os.replace(icon_tmp, dest / "app_logo.ico")
    return dest / "ShuaBaoLauncher.vbs"


def _rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _copy_bundle(bundle: Path, staging: Path) -> None:
    if staging.exists():
        _rmtree(staging)
    shutil.copytree(bundle, staging)


def _identity_matches_dir(release_dir: Path, identity: Mapping[str, Any]) -> bool:
    try:
        existing = verify_release_dir(release_dir, check_file_hashes=False)
    except InstallError:
        return False
    return (
        existing["source_sha"] == identity["source_sha"]
        and existing["release_channel"] == identity["release_channel"]
        and existing["exe_sha256"] == identity["exe_sha256"]
        and existing["release_manifest_sha256"] == identity["release_manifest_sha256"]
        and existing["version"] == identity["version"]
    )


def place_release(bundle: Path, install_root: Path | None = None) -> dict[str, Any]:
    """Copy a verified bundle into app-<id>. Does not switch current."""
    src = Path(bundle).resolve()
    root = Path(install_root).resolve() if install_root is not None else default_install_root()
    if not src.is_dir():
        raise InstallError(f"bundle 不是目录: {src}")
    identity = verify_release_dir(src)
    dir_name = release_dir_name(identity)
    dest = root / dir_name
    staging = root / (dir_name + STAGING_SUFFIX)
    root.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_dir() and _identity_matches_dir(dest, identity):
            verify_release_dir(dest)
            _rmtree(staging)
            return {"dir_name": dir_name, "path": str(dest), "identity": identity, "copied": False}
        raise InstallError(f"拒绝覆盖已存在的版本目录: {dest}")
    try:
        _copy_bundle(src, staging)
        staging_identity = verify_release_dir(staging)
        if release_dir_name(staging_identity) != dir_name:
            raise InstallError("staging identity 与目标目录名不一致")
        os.rename(staging, dest)
    except Exception:
        _rmtree(staging)
        raise
    verify_release_dir(dest)
    return {"dir_name": dir_name, "path": str(dest), "identity": identity, "copied": True}


def _iter_app_dirs(install_root: Path) -> list[Path]:
    if not Path(install_root).is_dir():
        return []
    found = []
    for item in Path(install_root).iterdir():
        if item.is_dir() and DIR_NAME_RE.match(item.name):
            found.append(item)
    return found


def prune_old_releases(install_root: Path, keep: set[str]) -> list[str]:
    removed: list[str] = []
    for item in _iter_app_dirs(install_root):
        if item.name in keep:
            continue
        _rmtree(item)
        removed.append(item.name)
    for item in Path(install_root).iterdir() if Path(install_root).is_dir() else []:
        if item.is_dir() and item.name.endswith(STAGING_SUFFIX):
            _rmtree(item)
            removed.append(item.name)
    return removed


def promote_release(install_root: Path, dir_name: str) -> dict[str, Any]:
    root = Path(install_root).resolve()
    if not DIR_NAME_RE.match(dir_name):
        raise InstallError(f"promote 目录名非法: {dir_name}")
    dest = root / dir_name
    identity = verify_release_dir(dest)
    pointer = None
    try:
        pointer = read_current(root)
    except InstallError:
        pointer = None
    previous = None
    if pointer is not None:
        if pointer["current"] == dir_name:
            previous = pointer.get("previous")
        else:
            old = root / pointer["current"]
            try:
                verify_release_dir(old, check_file_hashes=False)
                previous = pointer["current"]
            except InstallError:
                previous = pointer.get("previous")
    launcher = write_launcher(root)
    payload = write_current(root, identity, dir_name, previous)
    keep = {dir_name}
    if previous:
        keep.add(previous)
    removed = prune_old_releases(root, keep)
    payload["launcher"] = str(launcher)
    payload["pruned"] = removed
    payload["install_root"] = str(root)
    payload["path"] = str(dest)
    return payload


def install_release(
    bundle: Path,
    install_root: Path | None = None,
    *,
    switch_current: bool = True,
) -> dict[str, Any]:
    root = Path(install_root).resolve() if install_root is not None else default_install_root()
    placed = place_release(bundle, root)
    if not switch_current:
        placed["switched"] = False
        placed["install_root"] = str(root)
        return placed
    promoted = promote_release(root, placed["dir_name"])
    placed.update(promoted)
    placed["switched"] = True
    return placed


def rollback_release(install_root: Path | None = None) -> dict[str, Any]:
    root = Path(install_root).resolve() if install_root is not None else default_install_root()
    pointer = read_current(root)
    if pointer is None:
        raise InstallError("没有 current.json，无法回滚")
    previous = pointer.get("previous")
    if not previous:
        raise InstallError("没有可回滚的 previous 版本")
    dest = root / previous
    identity = verify_release_dir(dest)
    new_previous = pointer["current"]
    if new_previous == previous:
        raise InstallError("current 与 previous 相同，拒绝回滚")
    old = root / new_previous
    if old.is_dir():
        verify_release_dir(old, check_file_hashes=False)
    launcher = write_launcher(root)
    payload = write_current(root, identity, previous, new_previous)
    payload["launcher"] = str(launcher)
    payload["install_root"] = str(root)
    payload["path"] = str(dest)
    payload["rolled_back_from"] = new_previous
    return payload


def resolve_launch_target(install_root: Path | None = None) -> Path:
    root = Path(install_root).resolve() if install_root is not None else default_install_root()
    pointer = read_current(root)
    if pointer is None:
        raise LaunchError(f"缺少 current.json: {root / CURRENT_NAME}")
    dest = root / pointer["current"]
    try:
        identity = verify_release_dir(dest, check_file_hashes=False)
    except InstallError as exc:
        raise LaunchError(str(exc)) from exc
    expected_sha = str(pointer.get("current_source_sha") or "").strip().lower()
    expected_channel = str(pointer.get("current_release_channel") or "").strip()
    expected_manifest = str(pointer.get("current_release_manifest_sha256") or "").strip().lower()
    if expected_sha and identity["source_sha"] != expected_sha:
        raise LaunchError("current.json source_sha 与目标目录不一致")
    if expected_channel and identity["release_channel"] != expected_channel:
        raise LaunchError("current.json release_channel 与目标目录不一致")
    if expected_manifest and identity["release_manifest_sha256"] != expected_manifest:
        raise LaunchError("current.json manifest SHA 与目标目录不一致")
    exe = dest / APP_EXE
    if not exe.is_file():
        raise LaunchError(f"目标缺少 {APP_EXE}: {dest}")
    return exe


def launch_current(install_root: Path | None = None, *, dry_run: bool = False) -> Path:
    exe = resolve_launch_target(install_root)
    if dry_run:
        return exe
    kwargs: dict[str, Any] = {"cwd": str(exe.parent)}
    if sys.platform == "win32":
        kwargs["close_fds"] = False
        creation = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        kwargs["creationflags"] = creation
    subprocess.Popen([str(exe)], **kwargs)
    return exe


def describe_runtime_identity(exe_dir: Path | None = None) -> str:
    from shuabao import __version__

    version = __version__
    channel = ""
    source = ""
    manifest = ""
    candidates = []
    if exe_dir is not None:
        candidates.append(Path(exe_dir))
    if getattr(sys, "frozen", False) and getattr(sys, "executable", None):
        candidates.append(Path(sys.executable).resolve().parent)
    for base in candidates:
        path = base / "build_identity.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        version = str(payload.get("version") or version)
        channel = str(payload.get("release_channel") or channel)
        source = str(payload.get("source_sha") or source)
        manifest = str(payload.get("release_manifest_sha256") or manifest)
        break
    return (
        f"version={version} release_channel={channel or 'source'} "
        f"source_sha={source[:12] or 'unknown'} "
        f"manifest_sha={manifest[:12] or 'unknown'}"
    )


def _print_json(payload: Mapping[str, Any]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    install_p = sub.add_parser("install", help="复制 bundle 到 app-* 并可选切换 current")
    install_p.add_argument("--bundle", type=Path, required=True)
    install_p.add_argument("--install-root", type=Path, default=None)
    install_p.add_argument("--no-switch", action="store_true")
    place_p = sub.add_parser("place", help="只复制并校验，不切换 current")
    place_p.add_argument("--bundle", type=Path, required=True)
    place_p.add_argument("--install-root", type=Path, default=None)
    promote_p = sub.add_parser("promote", help="校验已就位目录后原子切换 current")
    promote_p.add_argument("--install-root", type=Path, default=None)
    promote_p.add_argument("--dir-name", required=True)
    rollback_p = sub.add_parser("rollback", help="切回 previous，不重建")
    rollback_p.add_argument("--install-root", type=Path, default=None)
    launch_p = sub.add_parser("launch", help="按 current.json 启动目标 EXE")
    launch_p.add_argument("--install-root", type=Path, default=None)
    launch_p.add_argument("--dry-run", action="store_true")
    status_p = sub.add_parser("status", help="打印 current pointer")
    status_p.add_argument("--install-root", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "install":
            result = install_release(args.bundle, args.install_root, switch_current=not args.no_switch)
        elif args.cmd == "place":
            result = place_release(args.bundle, args.install_root)
        elif args.cmd == "promote":
            result = promote_release(
                args.install_root if args.install_root is not None else default_install_root(),
                args.dir_name,
            )
        elif args.cmd == "rollback":
            result = rollback_release(args.install_root)
        elif args.cmd == "launch":
            exe = launch_current(args.install_root, dry_run=args.dry_run)
            result = {"ok": True, "exe": str(exe), "dry_run": bool(args.dry_run)}
        else:
            root = args.install_root if args.install_root is not None else default_install_root()
            pointer = read_current(root)
            result = {"ok": True, "install_root": str(Path(root).resolve()), "current": pointer}
        result.setdefault("ok", True)
        _print_json(result)
        return 0
    except (InstallError, LaunchError) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
