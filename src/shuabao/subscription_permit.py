"""Signed Ed25519 entitlement permit 集中验证（协议见 docs/SIGNED_ENTITLEMENT_PROTOCOL.md）。

本模块只依赖 stdlib + cryptography，不 import 任何业务模块。
Permit 的域绑定字段（product_id/audience/issuer）与固定期望值强校验，
任何缺失/未知/形状错误/域不匹配/超长有效期均 fail-closed。
"""
from __future__ import annotations

import base64
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

PERMIT_SCHEMA_VERSION = 1
SIGNATURE_ALGORITHM = "Ed25519"
CLOCK_SKEW = timedelta(seconds=300)
MAX_PERMIT_LIFETIME = timedelta(minutes=15)
PERMIT_PRODUCT_ID = "shuabao"
PERMIT_AUDIENCE = "live-runner"
PERMIT_ISSUER = "shuabao-subscription"

_REQUIRED_FIELDS = frozenset({
    "schema_version", "permit_id", "jti", "license_id", "device_id",
    "device_fingerprint", "release_channel", "source_sha",
    "release_manifest_sha256", "allowed_modes", "features", "issued_at",
    "expires_at", "nonce", "signature_algorithm", "key_id", "signature",
    "product_id", "audience", "issuer",
})
_STRING_FIELDS = (
    "permit_id", "jti", "license_id", "device_id", "device_fingerprint",
    "release_channel", "source_sha", "release_manifest_sha256", "nonce", "key_id",
    "product_id", "audience", "issuer",
)
_B64URL_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)

_VERIFIED_MARKER = object()


class PermitVerificationError(Exception):
    """Permit 校验失败；code 为稳定机器可读错误码（见协议文档）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class EntitlementPermit:
    """已通过结构校验的 permit；timestamp 保留原始字符串保证 canonical 稳定。"""

    schema_version: int
    product_id: str
    audience: str
    issuer: str
    permit_id: str
    jti: str
    license_id: str
    device_id: str
    device_fingerprint: str
    release_channel: str
    source_sha: str
    release_manifest_sha256: str
    allowed_modes: tuple[str, ...]
    features: tuple[str, ...]
    issued_at: str
    expires_at: str
    nonce: str
    signature_algorithm: str
    key_id: str
    signature: bytes

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object]) -> "EntitlementPermit":
        """严格解析；任何缺失/多余/形状错误抛 PermitVerificationError。"""
        if not isinstance(mapping, Mapping):
            raise PermitVerificationError("PERMIT_MALFORMED", "permit 必须是 JSON object")
        keys = set(mapping)
        missing = sorted(_REQUIRED_FIELDS - keys)
        unknown = sorted(keys - _REQUIRED_FIELDS)
        if missing or unknown:
            raise PermitVerificationError(
                "PERMIT_MALFORMED",
                f"字段缺失: {missing}; 未知字段: {unknown}",
            )
        if type(mapping["schema_version"]) is not int or mapping["schema_version"] != PERMIT_SCHEMA_VERSION:
            raise PermitVerificationError(
                "PERMIT_SCHEMA_UNKNOWN",
                f"不支持的 schema_version: {mapping['schema_version']!r}",
            )
        values: dict[str, object] = {}
        for name in _STRING_FIELDS:
            value = mapping[name]
            if not isinstance(value, str) or not value:
                raise PermitVerificationError("PERMIT_MALFORMED", f"{name} 必须是非空字符串")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise PermitVerificationError("PERMIT_MALFORMED", f"{name} 含非法 Unicode surrogate") from exc
            values[name] = value
        if values["permit_id"] != values["jti"]:
            raise PermitVerificationError("PERMIT_MALFORMED", "permit_id 与 jti 不一致")
        if values["device_id"] != values["device_fingerprint"]:
            raise PermitVerificationError("PERMIT_MALFORMED", "device_id 与 device_fingerprint 不一致")
        for domain_field, expected in (
            ("product_id", PERMIT_PRODUCT_ID),
            ("audience", PERMIT_AUDIENCE),
            ("issuer", PERMIT_ISSUER),
        ):
            if values[domain_field] != expected:
                raise PermitVerificationError(
                    "PERMIT_DOMAIN_MISMATCH",
                    f"{domain_field} 必须是 {expected!r}: {values[domain_field]!r}",
                )
        for name in ("allowed_modes", "features"):
            value = mapping[name]
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                raise PermitVerificationError("PERMIT_MALFORMED", f"{name} 必须是非空字符串列表")
            try:
                for item in value:
                    item.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise PermitVerificationError("PERMIT_MALFORMED", f"{name} 含非法 Unicode surrogate") from exc
            values[name] = tuple(value)
        if not values["allowed_modes"]:
            raise PermitVerificationError("PERMIT_MALFORMED", "allowed_modes 不能为空")
        for name in ("issued_at", "expires_at"):
            _parse_timestamp(str(mapping[name]), name)
            values[name] = mapping[name]
        if mapping["signature_algorithm"] != SIGNATURE_ALGORITHM:
            raise PermitVerificationError(
                "PERMIT_MALFORMED",
                f"signature_algorithm 必须是 {SIGNATURE_ALGORITHM}",
            )
        signature_text = mapping["signature"]
        if (
            not isinstance(signature_text, str)
            or not signature_text
            or not _B64URL_ALPHABET.issuperset(signature_text)
        ):
            raise PermitVerificationError("PERMIT_MALFORMED", "signature 必须是 base64url 无 padding 文本")
        try:
            signature = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        except (ValueError, TypeError) as exc:
            raise PermitVerificationError("PERMIT_MALFORMED", f"signature 解码失败: {exc}") from exc
        return cls(
            schema_version=PERMIT_SCHEMA_VERSION,
            product_id=str(values["product_id"]),
            audience=str(values["audience"]),
            issuer=str(values["issuer"]),
            permit_id=str(values["permit_id"]),
            jti=str(values["jti"]),
            license_id=str(values["license_id"]),
            device_id=str(values["device_id"]),
            device_fingerprint=str(values["device_fingerprint"]),
            release_channel=str(values["release_channel"]),
            source_sha=str(values["source_sha"]),
            release_manifest_sha256=str(values["release_manifest_sha256"]),
            allowed_modes=values["allowed_modes"],  # type: ignore[arg-type]
            features=values["features"],  # type: ignore[arg-type]
            issued_at=str(values["issued_at"]),
            expires_at=str(values["expires_at"]),
            nonce=str(values["nonce"]),
            signature_algorithm=SIGNATURE_ALGORITHM,
            key_id=str(values["key_id"]),
            signature=signature,
        )

    def canonical_payload(self) -> bytes:
        """被签名的字节串：UTF-8 JSON, sort_keys, 紧凑分隔符, 无 signature 字段。"""
        payload = {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "audience": self.audience,
            "issuer": self.issuer,
            "permit_id": self.permit_id,
            "jti": self.jti,
            "license_id": self.license_id,
            "device_id": self.device_id,
            "device_fingerprint": self.device_fingerprint,
            "release_channel": self.release_channel,
            "source_sha": self.source_sha,
            "release_manifest_sha256": self.release_manifest_sha256,
            "allowed_modes": list(self.allowed_modes),
            "features": list(self.features),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "signature_algorithm": self.signature_algorithm,
            "key_id": self.key_id,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class PermitVerificationContext:
    """本机启动时刻的绑定事实，由调用方（下一任务的 LIVE 边界）提供。"""

    device_id: str
    source_sha: str
    release_manifest_sha256: str
    release_channel: str
    mode_id: str
    now: datetime


@dataclass(frozen=True)
class VerifiedPermit:
    """验证通过后的可透传结果（下一任务接入 RunnerService/live_execute）。"""

    permit_id: str
    license_id: str
    device_id: str
    release_channel: str
    allowed_modes: tuple[str, ...]
    features: tuple[str, ...]
    expires_at: datetime
    key_id: str
    _marker: object | None = field(default=None, init=False, repr=False, compare=False)
    _issuer: object | None = field(default=None, init=False, repr=False, compare=False)


def is_verified_permit(value: object, *, issuer_token: object | None = None) -> bool:
    return (
        isinstance(value, VerifiedPermit)
        and value._marker is _VERIFIED_MARKER
        and (issuer_token is None or value._issuer is issuer_token)
    )


@dataclass(frozen=True)
class DevStartCapability:
    """仅显式 dev/off 模式的启动标记；不可由 permit 验证产生，不授权生产 LIVE。"""

    mode: str

    def __post_init__(self) -> None:
        if self.mode != "off":
            raise ValueError("DevStartCapability 仅对 mode='off' 有效")

    @classmethod
    def for_off(cls) -> "DevStartCapability":
        return cls(mode="off")


class InMemoryReplayStore:
    """进程内原子重放存储：permit_id 或 nonce 任一重复即拒绝。

    接口契约 claim(permit_id, nonce) -> bool（True = 首次记录），
    跨进程场景使用 PersistentReplayStore，未来 Redis/服务端存储按同一契约替换。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._permit_ids: set[str] = set()
        self._nonces: set[str] = set()

    def claim(self, permit_id: str, nonce: str) -> bool:
        with self._lock:
            if permit_id in self._permit_ids or nonce in self._nonces:
                return False
            self._permit_ids.add(permit_id)
            self._nonces.add(nonce)
            return True


class PersistentReplayStore:
    """SQLite 跨进程原子重放存储：同一契约 claim(permit_id, nonce) -> bool。

    单条 INSERT 依赖 UNIQUE(permit_id) 与 UNIQUE(nonce) 约束；
    SQLite 的 UNIQUE 检查在同一事务内原子完成，天然跨进程/多实例安全。
    """

    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        if path.parent != Path(""):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), timeout=30.0)
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS replay_claims ("
                "permit_id TEXT NOT NULL UNIQUE, nonce TEXT NOT NULL UNIQUE)"
            )

    def claim(self, permit_id: str, nonce: str) -> bool:
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO replay_claims (permit_id, nonce) VALUES (?, ?)",
                    (permit_id, nonce),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def close(self) -> None:
        self._conn.close()


class PermitVerifier:
    """Ed25519 permit 验证器。public_keys: key_id -> Ed25519PublicKey（空注册表=全拒绝）。"""

    def __init__(
        self,
        public_keys: Mapping[str, Ed25519PublicKey],
        replay_store: InMemoryReplayStore | PersistentReplayStore | None = None,
        *,
        issuer_token: object | None = None,
    ) -> None:
        self._public_keys = dict(public_keys)
        self._replay_store = replay_store
        self._issuer_token = issuer_token

    def verify(self, permit: EntitlementPermit, context: PermitVerificationContext) -> VerifiedPermit:
        if not isinstance(permit, EntitlementPermit):
            raise TypeError("verify 只接受 EntitlementPermit；StartPermission/dict 不构成授权")
        key = self._public_keys.get(permit.key_id)
        if key is None:
            raise PermitVerificationError("PERMIT_KEY_UNKNOWN", f"未知 key_id: {permit.key_id}")
        if (
            permit.product_id != PERMIT_PRODUCT_ID
            or permit.audience != PERMIT_AUDIENCE
            or permit.issuer != PERMIT_ISSUER
        ):
            # EntitlementPermit 可被直接构造绕过 from_mapping，验证层必须独立复核。
            raise PermitVerificationError(
                "PERMIT_DOMAIN_MISMATCH",
                f"permit 域绑定与本产品不符: product_id={permit.product_id!r}, "
                f"audience={permit.audience!r}, issuer={permit.issuer!r}",
            )
        now = _aware_utc(context.now)
        issued_at = _parse_timestamp(permit.issued_at, "issued_at")
        expires_at = _parse_timestamp(permit.expires_at, "expires_at")
        if issued_at > expires_at:
            raise PermitVerificationError(
                "PERMIT_MALFORMED",
                f"issued_at 晚于 expires_at: {permit.issued_at} > {permit.expires_at}",
            )
        if expires_at - issued_at > MAX_PERMIT_LIFETIME:
            raise PermitVerificationError(
                "PERMIT_LIFETIME_EXCEEDED",
                f"permit 有效期超过上限 {MAX_PERMIT_LIFETIME}: "
                f"{permit.issued_at} -> {permit.expires_at}",
            )
        if now > expires_at:
            raise PermitVerificationError("PERMIT_EXPIRED", f"permit 已于 {permit.expires_at} 过期")
        if issued_at - CLOCK_SKEW > now:
            raise PermitVerificationError("PERMIT_NOT_YET_VALID", f"issued_at 超出时钟偏差: {permit.issued_at}")
        if context.device_id != permit.device_id:
            raise PermitVerificationError("PERMIT_DEVICE_MISMATCH", "permit 绑定设备与当前设备不符")
        if context.source_sha != permit.source_sha:
            raise PermitVerificationError("PERMIT_SOURCE_MISMATCH", "permit 绑定 source 与当前构建不符")
        if context.release_manifest_sha256 != permit.release_manifest_sha256:
            raise PermitVerificationError("PERMIT_MANIFEST_MISMATCH", "permit 绑定 manifest 与当前构建不符")
        if context.release_channel != permit.release_channel:
            raise PermitVerificationError("PERMIT_CHANNEL_MISMATCH", "permit 绑定渠道与当前渠道不符")
        if context.mode_id not in permit.allowed_modes:
            raise PermitVerificationError("PERMIT_MODE_NOT_ALLOWED", f"mode {context.mode_id!r} 不在 permit 允许列表")
        try:
            key.verify(permit.signature, permit.canonical_payload())
        except InvalidSignature as exc:
            raise PermitVerificationError("PERMIT_SIGNATURE_INVALID", "Ed25519 签名验证失败") from exc
        if self._replay_store is not None and not self._replay_store.claim(permit.permit_id, permit.nonce):
            raise PermitVerificationError("PERMIT_REPLAY", "permit_id/nonce 已被使用")
        verified = VerifiedPermit(
            permit_id=permit.permit_id,
            license_id=permit.license_id,
            device_id=permit.device_id,
            release_channel=permit.release_channel,
            allowed_modes=permit.allowed_modes,
            features=permit.features,
            expires_at=expires_at,
            key_id=permit.key_id,
        )
        object.__setattr__(verified, "_marker", _VERIFIED_MARKER)
        object.__setattr__(verified, "_issuer", self._issuer_token)
        return verified


def _load_public_keys_bytes(data: bytes) -> dict[str, Ed25519PublicKey]:
    try:
        raw = json.loads(data.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("注册表根必须是 JSON object")
        entries = raw.get("keys")
        if not isinstance(entries, dict):
            raise ValueError('"keys" 必须是 object')
        keys: dict[str, Ed25519PublicKey] = {}
        for key_id, text in entries.items():
            key = load_der_public_key(base64.b64decode(text, validate=True))
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError(f"key {key_id!r} 不是 Ed25519 公钥")
            keys[str(key_id)] = key
        return keys
    except (UnicodeError, ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise PermitVerificationError(
            "PERMIT_KEY_REGISTRY_INVALID", f"公钥注册表不可用: {exc}"
        ) from exc


def load_public_keys(path: Path) -> dict[str, Ed25519PublicKey]:
    """读取 config/entitlement_public_keys.json 形如 {"keys": {"<key_id>": "<base64 SPKI DER>"}}。

    注册表为空返回 {}（PermitVerifier 对空注册表 fail-closed）；
    文件缺失/损坏抛 PERMIT_KEY_REGISTRY_INVALID。
    """
    try:
        return _load_public_keys_bytes(Path(path).read_bytes())
    except (OSError, PermitVerificationError) as exc:
        if isinstance(exc, PermitVerificationError):
            raise
        raise PermitVerificationError(
            "PERMIT_KEY_REGISTRY_INVALID", f"公钥注册表不可用: {exc}"
        ) from exc


def _parse_timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise PermitVerificationError("PERMIT_MALFORMED", f"{field} 必须是字符串")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise PermitVerificationError(
            "PERMIT_MALFORMED", f"{field} 必须是 UTC ISO-8601（YYYY-MM-DDTHH:MM:SSZ）: {value!r}"
        ) from exc
    return parsed.replace(tzinfo=timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise PermitVerificationError("PERMIT_MALFORMED", "context.now 必须带时区")
    return value.astimezone(timezone.utc)
