"""Runtime verification for signed release manifests.

The client contains no signing key. The build compiles an operator public-key
runtime hook into the EXE before shell imports. Source defaults remain empty;
packaged releases fail closed if that hook is absent, never trusting key files.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Mapping

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

MANIFEST_SCHEMA_VERSION = 1
PINNED_MANIFEST_PUBLIC_KEYS: Mapping[str, Ed25519PublicKey] = {}


class ReleaseManifestError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

def load_manifest_public_keys(path: Path) -> dict[str, Ed25519PublicKey]:
    """Load a registry for tooling/tests; runtime trust uses the compiled pin."""
    from shuabao.subscription_permit import PermitVerificationError, load_public_keys

    try:
        return load_public_keys(path)
    except PermitVerificationError as exc:
        raise ReleaseManifestError("MANIFEST_KEY_REGISTRY_INVALID", exc.message) from exc


def canonical_manifest_bytes(manifest: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, UnicodeEncodeError) as exc:
        raise ReleaseManifestError("MANIFEST_MALFORMED", f"发行清单不可规范化: {exc}") from exc


def canonical_manifest_sha256(manifest: Mapping[str, object]) -> str:
    """Canonical JSON UTF-8 SHA256；签名 envelope 与调用方统一使用该摘要。"""
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def _parse_manifest(data: bytes) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ReleaseManifestError("MANIFEST_MALFORMED", f"发行清单不可读取: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ReleaseManifestError("MANIFEST_MALFORMED", "发行清单 schema_version 不支持")
    return value


def _read_manifest(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReleaseManifestError("MANIFEST_MALFORMED", f"发行清单不可读取: {exc}") from exc
    return _parse_manifest(data), data
def _signature_envelope(raw: bytes | Mapping[str, object]) -> tuple[str, str, bytes]:
    try:
        envelope = json.loads(raw.decode("utf-8")) if isinstance(raw, bytes) else dict(raw)
        if not isinstance(envelope, dict):
            raise ValueError("签名 envelope 必须是 object")
        key_id = envelope.get("key_id")
        algorithm = envelope.get("algorithm")
        manifest_sha256 = envelope.get("manifest_sha256")
        encoded = envelope.get("signature")
        if (
            envelope.get("schema_version") != MANIFEST_SCHEMA_VERSION
            or not isinstance(key_id, str)
            or not key_id
            or algorithm != "Ed25519"
            or not isinstance(manifest_sha256, str)
            or len(manifest_sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in manifest_sha256)
            or not isinstance(encoded, str)
        ):
            raise ValueError("签名 envelope 字段无效")
        if not encoded or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in encoded):
            raise ValueError("signature 必须是 base64url 无 padding")
        signature = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if len(signature) != 64:
            raise ValueError("Ed25519 signature 长度无效")
        return key_id, manifest_sha256.lower(), signature
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ReleaseManifestError("MANIFEST_SIGNATURE_MALFORMED", f"签名 envelope 无效: {exc}") from exc


def verify_manifest_signature(
    manifest: Mapping[str, object], signature_envelope: bytes | Mapping[str, object], public_keys: Mapping[str, Ed25519PublicKey]
) -> str:
    key_id, manifest_sha256, signature = _signature_envelope(signature_envelope)
    canonical = canonical_manifest_bytes(manifest)
    if manifest_sha256 != canonical_manifest_sha256(manifest):
        raise ReleaseManifestError("MANIFEST_HASH_MISMATCH", "签名 envelope 的 manifest_sha256 不匹配")
    key = public_keys.get(key_id)
    if key is None:
        raise ReleaseManifestError("MANIFEST_KEY_UNKNOWN", f"未知 manifest key_id: {key_id}")
    try:
        key.verify(signature, canonical)
    except InvalidSignature as exc:
        raise ReleaseManifestError("MANIFEST_SIGNATURE_INVALID", "release_manifest Ed25519 签名验证失败") from exc
    return key_id

METADATA_FILE_EXCEPTIONS = frozenset({
    "release_manifest.json",
    "release_manifest.json.sig",
    "build_identity.json",
})


def _reject_reparse_point(path: Path, relative: str) -> None:
    # 拒绝 symlink/junction/reparse point：Windows 上 os.lstat 对 junction 与
    # 其他 reparse point 都带 FILE_ATTRIBUTE_REPARSE_POINT，POSIX 上 symlink
    # 由 S_ISLNK 判定；两个平台都 fail-closed。
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise ReleaseManifestError("MANIFEST_FILE_MISMATCH", f"发行文件不可读取: {relative}: {exc}") from exc
    if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ReleaseManifestError("MANIFEST_FILE_MISMATCH", f"发行文件不得是符号链接/junction/reparse point: {relative}")


def _verify_no_extra_files(package_root: Path, attested: set[str]) -> None:
    # 除逐项 hash/size 校验外，扫描 package_root 实际文件集。目录本身不是 manifest
    # 条目：只做 reparse point 检查；与 manifest 条目比较的是 regular files——
    # manifest 条目与三个元数据例外之外的任何文件（额外 DLL/plugin）一律拒绝。
    def _walk_error(err: os.error) -> None:
        raise ReleaseManifestError("MANIFEST_FILE_MISMATCH", f"发行目录不可扫描: {err}")

    try:
        for dirpath, dirnames, filenames in os.walk(package_root, onerror=_walk_error):
            for name in list(dirnames) + filenames:
                relative = Path(dirpath, name).relative_to(package_root).as_posix()
                _reject_reparse_point(Path(dirpath, name), relative)
            for name in filenames:
                relative = Path(dirpath, name).relative_to(package_root).as_posix()
                if relative not in attested and relative not in METADATA_FILE_EXCEPTIONS:
                    raise ReleaseManifestError("MANIFEST_EXTRA_FILE", f"发行包含有未签名文件: {relative}")
    except OSError as exc:
        raise ReleaseManifestError("MANIFEST_FILE_MISMATCH", f"发行目录不可扫描: {exc}") from exc





def verify_manifest_files(
    manifest: Mapping[str, object], package_root: Path, *, required_files: tuple[str, ...] = ()
) -> dict[str, bytes]:
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ReleaseManifestError("MANIFEST_MALFORMED", "files 必须是 list")
    verified_files: dict[str, bytes] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReleaseManifestError("MANIFEST_MALFORMED", "files entry 必须是 object")
        relative = entry.get("path")
        expected_hash = entry.get("sha256")
        expected_size = entry.get("size_bytes", entry.get("size"))
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ReleaseManifestError("MANIFEST_MALFORMED", f"非法文件路径: {relative!r}")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected_hash):
            raise ReleaseManifestError("MANIFEST_MALFORMED", f"非法文件 sha256: {relative}")
        if type(expected_size) is not int or expected_size < 0:
            raise ReleaseManifestError("MANIFEST_MALFORMED", f"非法文件大小: {relative}")
        normalized = relative.replace("\\", "/")
        target = package_root / Path(relative)
        _reject_reparse_point(target, normalized)
        try:
            data = target.read_bytes()
            actual_size = len(data)
            actual_hash = hashlib.sha256(data).hexdigest()
        except OSError as exc:
            raise ReleaseManifestError("MANIFEST_FILE_MISMATCH", f"发行文件不可读取: {relative}: {exc}") from exc
        if actual_size != expected_size or actual_hash.lower() != expected_hash.lower():
            raise ReleaseManifestError("MANIFEST_FILE_MISMATCH", f"发行文件哈希或大小不匹配: {relative}")
        verified_files[normalized] = data
    missing = [
        required for required in required_files
        if not any(
            path == required.replace("\\", "/")
            or path.endswith("/" + required.replace("\\", "/"))
            for path in verified_files
        )
    ]
    if missing:
        raise ReleaseManifestError("MANIFEST_FILE_UNATTESTED", f"发行清单未绑定必需文件: {missing}")
    _verify_no_extra_files(package_root, set(verified_files))
    return verified_files


def _verify_packaged_release(
    package_root: Path,
    *,
    pinned_keys: Mapping[str, Ed25519PublicKey] | None = None,
    required_files: tuple[str, ...] = (),
) -> tuple[dict[str, object], dict[str, bytes], bytes]:
    """Verify manifest signature and all attested files before trusting package data."""
    root = Path(package_root)
    keys = PINNED_MANIFEST_PUBLIC_KEYS if pinned_keys is None else pinned_keys
    if not keys:
        raise ReleaseManifestError("MANIFEST_TRUST_ANCHOR_MISSING", "未配置 operator Ed25519 manifest trust anchor")
    manifest_path = root / "release_manifest.json"
    signature_path = root / "release_manifest.json.sig"
    if not manifest_path.is_file():
        raise ReleaseManifestError("MANIFEST_MISSING", "缺少 release_manifest.json")
    if not signature_path.is_file():
        raise ReleaseManifestError("MANIFEST_SIGNATURE_MISSING", "缺少 release_manifest.json.sig")
    manifest, manifest_bytes = _read_manifest(manifest_path)
    try:
        signature = signature_path.read_bytes()
    except OSError as exc:
        raise ReleaseManifestError("MANIFEST_SIGNATURE_MISSING", f"签名不可读取: {exc}") from exc
    verify_manifest_signature(manifest, signature, keys)
    verified_files = verify_manifest_files(manifest, root, required_files=required_files)
    return manifest, verified_files, manifest_bytes


def verify_packaged_release(
    package_root: Path,
    *,
    pinned_keys: Mapping[str, Ed25519PublicKey] | None = None,
    required_files: tuple[str, ...] = (),
) -> dict[str, object]:
    return _verify_packaged_release(package_root, pinned_keys=pinned_keys, required_files=required_files)[0]


def verify_packaged_release_snapshot(
    package_root: Path,
    *,
    pinned_keys: Mapping[str, Ed25519PublicKey] | None = None,
    required_files: tuple[str, ...] = (),
) -> tuple[dict[str, object], dict[str, bytes], bytes]:
    return _verify_packaged_release(package_root, pinned_keys=pinned_keys, required_files=required_files)
