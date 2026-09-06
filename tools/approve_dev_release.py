"""Operator-side dev exact-release approval against the subscription control plane.

Closure B: reads the canonical identity of a freshly built, gate-verified,
**signature-verified** package and registers the exact tuple
``source_sha + release_manifest_sha256 + release_channel`` through the
existing admin API (``PUT/POST /v1/admin/releases``), then proves the write
with a read-after-write query against the public ``/v1/releases/status``.

Identity is computed with ``shuabao.release_signing.canonical_manifest_sha256``
— the single authority already used by ``build_release.ps1``,
``build_identity.json`` and the frozen ``live_execute._live_identity()``.
There is deliberately no second hashing scheme here.

Verification before approval (no second verifier; the existing
``verify_packaged_release_snapshot`` covers all of it):
- Ed25519 ``release_manifest.json.sig`` against the operator public-key
  registry (loaded from an explicit operator path / env — never from the
  package itself, which must not verify its own trust anchor);
- attested file hash/size for every manifest entry;
- extra unsigned files in the package root;
- ``build_identity.json`` agreement with the canonical manifest identity.

Channel policy: only ``dev`` / ``internal-pilot`` may ever be auto-approved.
``external-beta`` / ``release`` are always BLOCKED here — they go through an
independent human promotion / sign-off flow, never through this dev helper.

Security boundaries:
- admin credentials come only from the operator environment
  (``SHUABAO_SUBSCRIPTION_ADMIN_USER`` / ``SHUABAO_SUBSCRIPTION_ADMIN_PASSWORD``);
  they are never written to the registry, logs, package or client;
- endpoints must be HTTPS, or loopback HTTP for local verification;
- any verification, transport, auth or read-back failure exits non-zero
  (fail closed) and never touches the remote admin API;
- the runtime client keeps no self-approval capability.
"""
from __future__ import annotations

import argparse
import base64

import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shuabao.release_signing import (  # noqa: E402
    ReleaseManifestError,
    canonical_manifest_sha256,
    verify_packaged_release_snapshot,
)
from shuabao.subscription_permit import load_public_keys  # noqa: E402

APPROVED_MODES = ("lobby_hitch", "normal_farm", "follow_team")
CHANNELS = ("dev", "internal-pilot", "external-beta", "release")
# dev helper: only these two channels may ever be auto-approved.
# external-beta/release always BLOCKED — independent human promotion/sign-off.
OPERATOR_CHANNELS = ("dev", "internal-pilot")
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
ADMIN_USER_ENV = "SHUABAO_SUBSCRIPTION_ADMIN_USER"
ADMIN_PASSWORD_ENV = "SHUABAO_SUBSCRIPTION_ADMIN_PASSWORD"
BASE_URL_ENV = "SHUABAO_SUBSCRIPTION_BASE_URL"
PUBLIC_KEYS_ENV = "SHUABAO_MANIFEST_PUBLIC_KEYS_PATH"


class ApprovalError(RuntimeError):
    """Fail-closed rejection: never approve an unverified artifact."""


def _assert_path_outside_package(target_path: Path, package_root: Path) -> None:
    """Operator manifest trust anchor must live strictly OUTSIDE the package under approval.

    Symlinks, junctions, or relative tricks pointing back into the package must
    never allow the package to attest itself.
    """
    try:
        resolved_target = target_path.resolve()
        resolved_package = package_root.resolve()
    except (OSError, RuntimeError) as exc:
        raise ApprovalError(f"路径无法解析: {exc}") from exc

    # Check both the raw (absolute) path and the fully resolved target:
    for candidate in (target_path.absolute(), resolved_target):
        try:
            candidate.relative_to(resolved_package)
            is_inside = True
        except ValueError:
            is_inside = False
        if is_inside or candidate == resolved_package:
            raise ApprovalError(
                f"operator 公钥注册表 ({target_path}) 位于待审批发行包 ({package_root}) 内部；"
                "发行包不得作为自身的 trust anchor。"
            )


def _load_operator_keys(public_keys_path: str, *, package_root: Path | None = None) -> dict[str, object]:
    """Load the operator's manifest public-key registry strictly from OUTSIDE the package.

    The package must never be trusted to verify itself: the trust anchor comes
    from an explicit operator path or the existing build-time env variable
    (the same one ``build_release.ps1`` reads).
    """
    raw = str(public_keys_path or os.environ.get(PUBLIC_KEYS_ENV) or "").strip()
    if not raw:
        raise ApprovalError(
            f"缺少 operator manifest 公钥注册表（--public-keys 或 {PUBLIC_KEYS_ENV}）；"
            "不得信任 package 自带密钥验证自身"
        )
    key_path = Path(raw)
    if package_root is not None:
        _assert_path_outside_package(key_path, package_root)
    try:
        keys = load_public_keys(key_path)
    except Exception as exc:
        raise ApprovalError(f"operator 公钥注册表不可用: {exc}") from exc
    if not keys:
        raise ApprovalError("operator 公钥注册表为空")
    return keys


def load_package_identity(package_root: Path, *, public_keys_path: str = "") -> dict[str, str]:
    """Verify the real package (signature + attested files + no extras), then
    derive the canonical identity and cross-check ``build_identity.json``."""
    root = Path(package_root)
    keys = _load_operator_keys(public_keys_path, package_root=root)
    try:
        manifest, _verified_files, _manifest_bytes = verify_packaged_release_snapshot(
            root, pinned_keys=keys,
        )
    except ReleaseManifestError as exc:
        raise ApprovalError(f"发行包验证失败（{exc.code}）: {exc.message}") from exc
    source_sha = str(manifest.get("source_sha") or "").strip().lower()
    channel = str(manifest.get("release_channel") or "").strip()
    if not HEX40.fullmatch(source_sha):
        raise ApprovalError(f"manifest source_sha 非法: {source_sha!r}")
    if channel not in CHANNELS:
        raise ApprovalError(f"manifest release_channel 非法: {channel!r}")
    manifest_sha = canonical_manifest_sha256(manifest)
    if not HEX64.fullmatch(manifest_sha):
        raise ApprovalError("canonical manifest sha256 计算失败")

    identity = {
        "source_sha": source_sha,
        "release_manifest_sha256": manifest_sha,
        "release_channel": channel,
        "package_root": str(root),
    }
    identity_path = root / "build_identity.json"
    if not identity_path.is_file():
        raise ApprovalError(f"缺少 build_identity.json: {identity_path}")
    try:
        build_identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApprovalError(f"build_identity.json 不可读: {exc}") from exc
    if str(build_identity.get("release_manifest_sha256") or "").lower() != manifest_sha:
        raise ApprovalError("build_identity manifest SHA 与 canonical manifest 不一致")
    if str(build_identity.get("source_sha") or "").lower() != source_sha:
        raise ApprovalError("build_identity source_sha 与 manifest 不一致")
    if str(build_identity.get("release_channel") or "") != channel:
        raise ApprovalError("build_identity release_channel 与 manifest 不一致")
    return identity


def _validate_modes(modes: list[str]) -> list[str]:
    if not modes:
        raise ApprovalError("allowed_modes 不能为空")
    unknown = sorted(set(modes) - set(APPROVED_MODES))
    if unknown:
        raise ApprovalError(f"未知 mode: {unknown}")
    return sorted(set(modes))


def _endpoint_or_die(base_url: str) -> str:
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        raise ApprovalError(f"订阅服务地址未配置（{BASE_URL_ENV} 或 --base-url）")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as exc:
        raise ApprovalError(f"订阅服务地址非法: {exc}") from exc
    norm_host = (parsed.hostname or "").lower().rstrip(".")
    if not norm_host:
        raise ApprovalError("订阅服务地址缺少有效 hostname")

    is_loopback = False
    if norm_host == "localhost":
        is_loopback = True
    else:
        # Strip IPv6 literal brackets if present
        ip_str = norm_host.strip("[]")
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            is_loopback = ip_obj.is_loopback
        except ValueError:
            # Ordinary DNS hostname (even if prefix is 127.) is NOT loopback
            is_loopback = False

    if parsed.scheme == "https" and norm_host and not parsed.username and not parsed.password:
        return raw
    if parsed.scheme == "http" and is_loopback and not parsed.username and not parsed.password:
        return raw
    raise ApprovalError("订阅服务地址必须为 HTTPS（或 real IP loopback HTTP），且不得内嵌凭据")


def _request(method: str, url: str, *, body: bytes | None = None, headers=None, timeout: float):
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        raise ApprovalError(f"{method} {urllib.parse.urlsplit(url).path} 失败: HTTP {exc.code} {detail}".strip()) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ApprovalError(f"{method} {urllib.parse.urlsplit(url).path} 不可达: {type(exc).__name__}") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ApprovalError(f"{method} {urllib.parse.urlsplit(url).path} 返回非 JSON") from exc


def push_release_policy(
    identity: dict[str, str],
    *,
    base_url: str,
    modes: list[str],
    timeout: float = 15.0,
) -> dict[str, object]:
    """Upsert the exact policy through the existing admin API (Basic auth from env)."""
    endpoint = _endpoint_or_die(base_url)
    user = str(os.environ.get(ADMIN_USER_ENV) or "").strip()
    password = str(os.environ.get(ADMIN_PASSWORD_ENV) or "")
    if not user or not password:
        raise ApprovalError(
            f"缺少运维凭据：{ADMIN_USER_ENV}/{ADMIN_PASSWORD_ENV} 只能来自仓外安全环境"
        )
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    body = json.dumps(
        {
            "source_sha": identity["source_sha"],
            "release_manifest_sha256": identity["release_manifest_sha256"],
            "release_channel": identity["release_channel"],
            "allowed_modes": modes,
            "operator_note": "dev-build auto approval",
        }
    ).encode("utf-8")
    response = _request(
        "PUT",
        f"{endpoint}/v1/admin/releases",
        body=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        },
        timeout=timeout,
    )
    if response.get("ok") is not True:
        raise ApprovalError("admin upsert 未返回 ok=true")
    return response


def verify_release_approved(
    identity: dict[str, str],
    *,
    base_url: str,
    modes: list[str],
    timeout: float = 15.0,
) -> dict[str, object]:
    """Read-after-write against the public status endpoint; fail closed unless approved."""
    endpoint = _endpoint_or_die(base_url)
    query = urllib.parse.urlencode(
        {
            "source_sha": identity["source_sha"],
            "release_manifest_sha256": identity["release_manifest_sha256"],
            "release_channel": identity["release_channel"],
        }
    )
    status = _request("GET", f"{endpoint}/v1/releases/status?{query}", timeout=timeout)
    if status.get("approved") is not True:
        raise ApprovalError(f"read-after-write 未批准: status={status.get('status')!r}")
    if str(status.get("source_sha") or "").lower() != identity["source_sha"]:
        raise ApprovalError("read-after-write source_sha 不符")
    if str(status.get("release_manifest_sha256") or "").lower() != identity["release_manifest_sha256"]:
        raise ApprovalError("read-after-write manifest sha 不符")
    if str(status.get("release_channel") or "") != identity["release_channel"]:
        raise ApprovalError("read-after-write channel 不符")
    if status.get("blocked") is True:
        raise ApprovalError("read-after-write: 该 release 被标记 blocked")
    granted = {str(m) for m in (status.get("allowed_modes") or [])}
    missing = sorted(set(modes) - granted)
    if missing:
        raise ApprovalError(f"read-after-write 缺少模式授权: {missing}")
    return status


def write_audit_record(identity: dict[str, str], *, registry_path: Path, modes: list[str]) -> None:
    """Local operator audit copy only; the control plane is the authority."""
    entries: list[dict[str, object]] = []
    if registry_path.is_file():
        try:
            loaded = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ApprovalError(f"本地审批记录不可读: {exc}") from exc
        if isinstance(loaded, list):
            entries = [e for e in loaded if isinstance(e, dict)]
    key = (identity["source_sha"], identity["release_manifest_sha256"], identity["release_channel"])
    entries = [
        e for e in entries
        if (str(e.get("source_sha")), str(e.get("release_manifest_sha256")), str(e.get("release_channel"))) != key
    ]
    entries.append({
        "source_sha": identity["source_sha"],
        "release_manifest_sha256": identity["release_manifest_sha256"],
        "release_channel": identity["release_channel"],
        "allowed_modes": modes,
        "package_root": identity["package_root"],
    })
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path, help="已验证发行包目录（含 release_manifest.json）")
    parser.add_argument("--registry", type=Path, help="可选：本地运维审计记录 JSON")
    parser.add_argument("--modes", default=",".join(APPROVED_MODES))
    parser.add_argument("--base-url", default="", help=f"默认读 {BASE_URL_ENV}")
    parser.add_argument("--public-keys", default="", help=f"operator manifest 公钥注册表（默认读 {PUBLIC_KEYS_ENV}）")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    try:
        # 1. Verify the real package first: signature, attested files, extras,
        #    build_identity agreement. No remote API call on any failure.
        identity = load_package_identity(
            args.package, public_keys_path=args.public_keys,
        )
        modes = _validate_modes([m.strip() for m in args.modes.split(",") if m.strip()])
        # 2. Hard channel gate: external-beta/release are never auto-approved.
        if identity["release_channel"] not in OPERATOR_CHANNELS:
            raise ApprovalError(
                f"渠道 {identity['release_channel']!r} 禁止本工具自动批准；"
                "external-beta/release 必须走独立人工 promotion/sign-off 流程"
            )
        # 3. Remote push + verified read-back.
        base_url = args.base_url or os.environ.get(BASE_URL_ENV, "")
        push_release_policy(identity, base_url=base_url, modes=modes, timeout=args.timeout)
        status = verify_release_approved(identity, base_url=base_url, modes=modes, timeout=args.timeout)
        if args.registry is not None:
            write_audit_record(identity, registry_path=args.registry, modes=modes)
        print(
            "approved: "
            f"source_sha={identity['source_sha']} "
            f"release_manifest_sha256={identity['release_manifest_sha256']} "
            f"channel={identity['release_channel']} modes={modes} "
            f"status={status.get('status')!r}"
        )
        return 0
    except ApprovalError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
