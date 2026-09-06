"""Operator-side dev exact-release approval against the subscription control plane.

Closure B: reads the canonical identity of a freshly built, gate-verified
package and registers the exact tuple
``source_sha + release_manifest_sha256 + release_channel`` through the
existing admin API (``PUT/POST /v1/admin/releases``), then proves the write
with a read-after-write query against the public ``/v1/releases/status``.

Identity is computed with ``shuabao.release_signing.canonical_manifest_sha256``
— the single authority already used by ``build_release.ps1``,
``build_identity.json`` and the frozen ``live_execute._live_identity()``.
There is deliberately no second hashing scheme here.

Security boundaries:
- admin credentials come only from the operator environment
  (``SHUABAO_SUBSCRIPTION_ADMIN_USER`` / ``SHUABAO_SUBSCRIPTION_ADMIN_PASSWORD``);
  they are never written to the registry, logs, package or client;
- endpoints must be HTTPS, or loopback HTTP for local verification;
- ``dev`` / ``internal-pilot`` only unless ``--allow-channel`` is passed;
- any transport, auth or read-back failure exits non-zero (fail closed);
- the runtime client keeps no self-approval capability.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shuabao.release_signing import canonical_manifest_sha256  # noqa: E402

APPROVED_MODES = ("lobby_hitch", "normal_farm", "follow_team")
CHANNELS = ("dev", "internal-pilot", "external-beta", "release")
OPERATOR_CHANNELS = ("dev", "internal-pilot")
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
ADMIN_USER_ENV = "SHUABAO_SUBSCRIPTION_ADMIN_USER"
ADMIN_PASSWORD_ENV = "SHUABAO_SUBSCRIPTION_ADMIN_PASSWORD"
BASE_URL_ENV = "SHUABAO_SUBSCRIPTION_BASE_URL"


class ApprovalError(RuntimeError):
    """Fail-closed rejection: never approve an unverified artifact."""


def load_package_identity(package_root: Path) -> dict[str, str]:
    """Read the exact identity from the real package bytes via the canonical authority."""
    manifest_path = package_root / "release_manifest.json"
    if not manifest_path.is_file():
        raise ApprovalError(f"缺少 release_manifest.json: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApprovalError(f"release_manifest.json 不可读: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ApprovalError("release_manifest.json 根必须是 JSON object")
    source_sha = str(manifest.get("source_sha") or "").strip().lower()
    channel = str(manifest.get("release_channel") or "").strip()
    if not HEX40.fullmatch(source_sha):
        raise ApprovalError(f"manifest source_sha 非法: {source_sha!r}")
    if channel not in CHANNELS:
        raise ApprovalError(f"manifest release_channel 非法: {channel!r}")
    manifest_sha = canonical_manifest_sha256(manifest)
    if not HEX64.fullmatch(manifest_sha):
        raise ApprovalError("canonical manifest sha256 计算失败")
    return {
        "source_sha": source_sha,
        "release_manifest_sha256": manifest_sha,
        "release_channel": channel,
        "package_root": str(package_root),
    }


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
    host = (parsed.hostname or "").strip("[]").lower().rstrip(".")
    loopback = host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")
    if parsed.scheme == "https" and host and not parsed.username and not parsed.password:
        return raw
    if parsed.scheme == "http" and loopback:
        return raw
    raise ApprovalError("订阅服务地址必须为 HTTPS（或 loopback HTTP），且不得内嵌凭据")


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
    import base64

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
    entries.append({**identity, "allowed_modes": modes, "package_root": identity["package_root"]})
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
    parser.add_argument("--allow-channel", action="store_true", help="显式允许非 dev/internal-pilot 渠道")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    try:
        identity = load_package_identity(args.package)
        modes = _validate_modes([m.strip() for m in args.modes.split(",") if m.strip()])
        channel = identity["release_channel"]
        if channel not in OPERATOR_CHANNELS and not args.allow_channel:
            raise ApprovalError(
                f"渠道 {channel!r} 需要 --allow-channel 显式确认（外发渠道走人工签核，不自动批准）"
            )
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
