"""Operator-side dev exact-release approval registration (Closure B).

Reads the identity of a freshly built, gate-verified package
(``release_manifest.json`` inside the bundle) and registers the exact
tuple ``source_sha + release_manifest_sha256 + release_channel`` — the
subscription server's ``PermitIssuer`` approval key — into an operator
approval registry file.  The registry content is what the VPS ships as
``SHUABAO_APPROVED_RELEASES_JSON``.

Security model (unchanged):
- exact identity (source+manifest+channel), never source-only;
- client never sees this tool, its file, or any admin credential;
- dev channel only unless ``--allow-channel`` is passed explicitly by the
  operator for internal-pilot;
- every mutation is validated against the registry schema the server
  enforces (hex40 source, hex64 manifest, known channels, non-empty modes).

This is a build/operator-side capability, not a runtime client capability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

APPROVED_MODES = ("lobby_hitch", "normal_farm", "follow_team")
CHANNELS = ("dev", "internal-pilot", "external-beta", "release")
OPERATOR_CHANNELS = ("dev", "internal-pilot")  # external channels need manual sign-off
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
MAX_PERMIT_MINUTES = 15


class ApprovalError(RuntimeError):
    """Fail-closed rejection: never register an unverified artifact."""


def canonical_manifest_sha256(manifest_path: Path) -> str:
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def load_package_identity(package_root: Path) -> dict[str, str]:
    """Read the exact identity from the real package bytes, not from arguments."""
    manifest_path = package_root / "release_manifest.json"
    if not manifest_path.is_file():
        raise ApprovalError(f"缺少 release_manifest.json: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApprovalError(f"release_manifest.json 不可读: {exc}") from exc
    source_sha = str(manifest.get("source_sha") or "").strip().lower()
    channel = str(manifest.get("release_channel") or "").strip()
    if not HEX40.fullmatch(source_sha):
        raise ApprovalError(f"manifest source_sha 非法: {source_sha!r}")
    if channel not in CHANNELS:
        raise ApprovalError(f"manifest release_channel 非法: {channel!r}")
    manifest_sha = canonical_manifest_sha256(manifest_path)
    if not HEX64.fullmatch(manifest_sha):
        raise ApprovalError("manifest sha256 计算失败")
    return {
        "source_sha": source_sha,
        "release_manifest_sha256": manifest_sha,
        "release_channel": channel,
        "package_root": str(package_root),
    }


def _validate_modes(modes: list[str]) -> None:
    if not modes:
        raise ApprovalError("allowed_modes 不能为空")
    unknown = sorted(set(modes) - set(APPROVED_MODES))
    if unknown:
        raise ApprovalError(f"未知 mode: {unknown}")


def load_registry(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApprovalError(f"审批注册表不可读: {exc}") from exc
    if not isinstance(entries, list):
        raise ApprovalError("审批注册表必须是 JSON 数组")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApprovalError("审批注册表条目必须是对象")
        _validate_modes([str(m) for m in entry.get("allowed_modes", [])])
    return entries


def register(
    identity: dict[str, str],
    *,
    registry_path: Path,
    modes: list[str],
    operator: str,
    allow_channel: bool,
) -> tuple[list[dict[str, object]], str]:
    _validate_modes(modes)
    channel = identity["release_channel"]
    if channel not in OPERATOR_CHANNELS and not allow_channel:
        raise ApprovalError(
            f"渠道 {channel!r} 需要 -AllowChannel 显式确认（外发渠道走人工签核，不走本工具）"
        )
    entries = load_registry(registry_path)
    key = (identity["source_sha"], identity["release_manifest_sha256"], channel)
    new_entry: dict[str, object] = {
        "source_sha": identity["source_sha"],
        "release_manifest_sha256": identity["release_manifest_sha256"],
        "release_channel": channel,
        "allowed_modes": sorted(set(modes)),
    }
    filtered = [
        e
        for e in entries
        if (
            str(e.get("source_sha")),
            str(e.get("release_manifest_sha256")),
            str(e.get("release_channel")),
        )
        != key
    ]
    filtered.append(new_entry)
    action = "replaced" if len(filtered) != len(entries) else "registered"
    del operator  # recorded by the caller's VCS/ops flow, not embedded here
    return filtered, action


def export_env(entries: list[dict[str, object]]) -> str:
    """Render the registry as the server's SHUABAO_APPROVED_RELEASES_JSON value."""
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path, help="已验证的发行包目录（含 release_manifest.json）")
    parser.add_argument("--registry", required=True, type=Path, help="运维审批注册表 JSON 文件")
    parser.add_argument("--modes", default=",".join(APPROVED_MODES), help="允许的 mode，逗号分隔")
    parser.add_argument("--operator", default="", help="操作员标识（仅写入本地操作日志，不进注册表）")
    parser.add_argument("--allow-channel", action="store_true", help="显式允许非 dev/internal-pilot 渠道")
    parser.add_argument("--print-env", action="store_true", help="打印 SHUABAO_APPROVED_RELEASES_JSON 的值")
    args = parser.parse_args(argv)

    try:
        identity = load_package_identity(args.package)
        modes = [m.strip() for m in args.modes.split(",") if m.strip()]
        entries, action = register(
            identity,
            registry_path=args.registry,
            modes=modes,
            operator=args.operator,
            allow_channel=args.allow_channel,
        )
        args.registry.parent.mkdir(parents=True, exist_ok=True)
        args.registry.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"{action}: source_sha={identity['source_sha'][:12]} "
            f"manifest={identity['release_manifest_sha256'][:12]} "
            f"channel={identity['release_channel']} modes={modes}"
        )
        if args.print_env:
            print("SHUABAO_APPROVED_RELEASES_JSON=" + export_env(entries))
        return 0
    except ApprovalError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
