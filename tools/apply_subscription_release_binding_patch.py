#!/usr/bin/env python3
"""One-shot deterministic wiring for release-bound subscription permits."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str, label: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one exact match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def patch_subscription_client() -> None:
    path = "src/shuabao/subscription_client.py"
    replace_once(
        path,
        'VALID_MODES = {"off", "shadow", "enforce"}\n',
        '''VALID_MODES = {"off", "shadow", "enforce"}
PERMIT_REQUEST_FIELDS = (
    "source_sha",
    "release_manifest_sha256",
    "release_channel",
    "mode_id",
)
''',
        "permit request fields",
    )
    replace_once(
        path,
        '''    return f"{prefix}: {type(exc).__name__}"


def validate_entitlement(
''',
        '''    return f"{prefix}: {type(exc).__name__}"


def _normalize_permit_request(
    value: Mapping[str, object] | None,
) -> dict[str, str] | None:
    """Return the exact server permit-request shape or reject it before I/O."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != set(PERMIT_REQUEST_FIELDS):
        raise ValueError("permit request fields mismatch")
    normalized: dict[str, str] = {}
    for field in PERMIT_REQUEST_FIELDS:
        raw = value.get(field)
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"permit request field invalid: {field}")
        normalized[field] = raw.strip()
    return normalized


def validate_entitlement(
''',
        "permit request normalizer",
    )
    replace_once(
        path,
        '''def validate_entitlement(
    license_key: str,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
''',
        '''def validate_entitlement(
    license_key: str,
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    permit_request: Mapping[str, object] | None = None,
) -> dict[str, Any]:
''',
        "validate entitlement signature",
    )
    replace_once(
        path,
        '''    body = {
        "license_key": key,
        "hardware": {
            "fingerprint": fingerprint,
            "components": {},
            "platform": "windows",
            "hostname": socket.gethostname() or None,
        },
    }
''',
        '''    try:
        normalized_permit_request = _normalize_permit_request(permit_request)
    except (TypeError, ValueError):
        return {
            "valid": False,
            "status": "UNKNOWN",
            "code": "CONFIG_PERMIT_REQUEST_INVALID",
            "message": "LIVE permit 发行身份字段无效",
        }
    body: dict[str, object] = {
        "license_key": key,
        "hardware": {
            "fingerprint": fingerprint,
            "components": {},
            "platform": "windows",
            "hostname": socket.gethostname() or None,
        },
    }
    if normalized_permit_request is not None:
        body["permit_request"] = normalized_permit_request
''',
        "validate entitlement request body",
    )
    replace_once(
        path,
        '''def check_start_permission(
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
) -> StartPermission:
''',
        '''def check_start_permission(
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., Any] | None = None,
    permit_request: Mapping[str, object] | None = None,
) -> StartPermission:
''',
        "check start permission signature",
    )
    replace_once(
        path,
        '''    payload = validate_entitlement(license_key, env=source, opener=opener)
''',
        '''    if permit_request is None:
        payload = validate_entitlement(license_key, env=source, opener=opener)
    else:
        payload = validate_entitlement(
            license_key,
            env=source,
            opener=opener,
            permit_request=permit_request,
        )
''',
        "check start permission request forwarding",
    )
    replace_once(
        path,
        '''        "CONFIG_BASE_URL_INVALID", "ENTITLEMENT_UNREACHABLE", "ENTITLEMENT_MALFORMED",
''',
        '''        "CONFIG_BASE_URL_INVALID", "CONFIG_PERMIT_REQUEST_INVALID",
        "ENTITLEMENT_UNREACHABLE", "ENTITLEMENT_MALFORMED",
''',
        "permit request configuration error",
    )


def patch_live_identity() -> None:
    path = "src/shuabao/shell/live_execute.py"
    replace_once(
        path,
        '''def resolve_live_permission(permission: Any, *, mode_id: str, root: Path) -> DevStartCapability | VerifiedPermit:
''',
        '''def live_permit_request_context(root: Path, mode_id: str) -> dict[str, str] | None:
    """Return only an authenticated frozen release identity for permit issuance."""
    identity = _live_identity(Path(root))
    requested_mode = str(mode_id or "").strip()
    if (
        not identity.packaged
        or not identity.source_sha
        or not identity.manifest_sha
        or not identity.release_channel
        or not requested_mode
    ):
        return None
    return {
        "source_sha": identity.source_sha,
        "release_manifest_sha256": identity.manifest_sha,
        "release_channel": identity.release_channel,
        "mode_id": requested_mode,
    }


def resolve_live_permission(permission: Any, *, mode_id: str, root: Path) -> DevStartCapability | VerifiedPermit:
''',
        "live permit request context",
    )


def patch_runner_service() -> None:
    path = "src/shuabao/shell/runner_service.py"
    replace_once(
        path,
        '''    execute_runtime_mediator,
    live_lock_path,
    resolve_live_permission,
)
''',
        '''    execute_runtime_mediator,
    live_lock_path,
    live_permit_request_context,
    resolve_live_permission,
)
''',
        "runner live context import",
    )
    replace_once(
        path,
        '''        if permission is None:
            permission = permission_checker() if permission_checker is not None else check_start_permission()
        permission = resolve_live_permission(permission, mode_id=mode_id, root=self.root)
''',
        '''        if permission is None:
            if permission_checker is not None:
                permission = permission_checker()
            else:
                permit_request = live_permit_request_context(self.root, mode_id)
                permission = (
                    check_start_permission(permit_request=permit_request)
                    if permit_request is not None
                    else check_start_permission()
                )
        permission = resolve_live_permission(permission, mode_id=mode_id, root=self.root)
''',
        "runner release-bound permission request",
    )


def patch_dashboard_facade() -> None:
    path = "src/shuabao/shell/dashboard_facade.py"
    replace_once(
        path,
        '''from shuabao.shell.runner_service import live_lock_busy
from shuabao.shell.runtime_status import runtime_status_from_mediator
''',
        '''from shuabao.shell.runner_service import live_lock_busy
from shuabao.shell.live_execute import live_permit_request_context
from shuabao.shell.runtime_status import runtime_status_from_mediator
''',
        "dashboard live context import",
    )
    replace_once(
        path,
        '''        self._subscription_cache_key: tuple[str, str, str, str] | None = None
''',
        '''        self._subscription_cache_key: tuple[str, ...] | None = None
''',
        "dashboard subscription cache type",
    )
    replace_once(
        path,
        '''    def _subscription_key(self) -> tuple[str, str, str, str]:
        key = str(os.environ.get(SUBSCRIPTION_LICENSE_KEY_ENV) or "").strip()
        endpoint = str(os.environ.get("SHUABAO_SUBSCRIPTION_BASE_URL") or "").strip()
        mode = str(os.environ.get("SHUABAO_SUBSCRIPTION_MODE") or "").strip().lower()
        # Keep the raw key out of the in-memory cache key and diagnostic data.
        key_digest = hashlib.sha256(key.encode("utf-8")).hexdigest() if key else ""
        return mode, endpoint, key_digest, str(os.environ.get("SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT") or "").strip()

    def _subscription_permission(self, *, force: bool = False):
        key = self._subscription_key()
        now = time.monotonic()
        if (
            not force
            and self._subscription_cache is not None
            and key == self._subscription_cache_key
            and now - self._subscription_cache_at < self._subscription_cache_ttl_s
        ):
            return self._subscription_cache
        permission = check_start_permission()
        self._subscription_cache_key = key
        self._subscription_cache_at = now
        self._subscription_cache = permission
        return permission
''',
        '''    def _subscription_key(
        self,
        permit_request: Mapping[str, object] | None = None,
    ) -> tuple[str, ...]:
        key = str(os.environ.get(SUBSCRIPTION_LICENSE_KEY_ENV) or "").strip()
        endpoint = str(os.environ.get("SHUABAO_SUBSCRIPTION_BASE_URL") or "").strip()
        mode = str(os.environ.get("SHUABAO_SUBSCRIPTION_MODE") or "").strip().lower()
        # Keep the raw key out of the in-memory cache key and diagnostic data.
        key_digest = hashlib.sha256(key.encode("utf-8")).hexdigest() if key else ""
        base = (
            mode,
            endpoint,
            key_digest,
            str(os.environ.get("SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT") or "").strip(),
        )
        context = tuple(
            str((permit_request or {}).get(field) or "").strip()
            for field in (
                "source_sha",
                "release_manifest_sha256",
                "release_channel",
                "mode_id",
            )
        )
        return base + context

    def _permit_request_context(self, mode_id: str | None) -> dict[str, str] | None:
        requested_mode = str(mode_id or "").strip()
        if not requested_mode:
            return None
        root = self._root
        if root is None and self._runner is not None:
            candidate = getattr(self._runner, "root", None)
            root = Path(candidate) if candidate is not None else None
        if root is None:
            return None
        return live_permit_request_context(root, requested_mode)

    def _subscription_permission(
        self,
        *,
        force: bool = False,
        mode_id: str | None = None,
    ):
        permit_request = self._permit_request_context(mode_id)
        key = self._subscription_key(permit_request)
        now = time.monotonic()
        if (
            not force
            and self._subscription_cache is not None
            and key == self._subscription_cache_key
            and now - self._subscription_cache_at < self._subscription_cache_ttl_s
        ):
            return self._subscription_cache
        permission = (
            check_start_permission(permit_request=permit_request)
            if permit_request is not None
            else check_start_permission()
        )
        self._subscription_cache_key = key
        self._subscription_cache_at = now
        self._subscription_cache = permission
        return permission
''',
        "dashboard release-bound permission cache",
    )
    replace_once(
        path,
        '''        permission = self._subscription_cache
        if permission is None or self._subscription_cache_key != self._subscription_key():
            return {"active": False, "status": "待校验", "expires_at": ""}
''',
        '''        permission = self._subscription_cache
        base_key = self._subscription_key()[:4]
        cached_base = self._subscription_cache_key[:4] if self._subscription_cache_key else None
        if permission is None or cached_base != base_key:
            return {"active": False, "status": "待校验", "expires_at": ""}
''',
        "dashboard subscription DTO cache scope",
    )
    replace_once(
        path,
        '''        permission = self._subscription_permission()
        runtime_root_ok = self._root is None or Path(self._root).is_dir() or self._runner is not None
''',
        '''        permission = self._subscription_permission(mode_id=mode_id)
        runtime_root_ok = self._root is None or Path(self._root).is_dir() or self._runner is not None
''',
        "preflight mode-bound permission",
    )
    replace_once(
        path,
        '''        permission = self._subscription_permission(force=True)
        pre = json.loads(self.validate_preflight(mode_id_json))
''',
        '''        requested_mode_id = self._parse_keyed(mode_id_json, "mode_id")
        permission = self._subscription_permission(
            force=True,
            mode_id=requested_mode_id,
        )
        pre = json.loads(self.validate_preflight(mode_id_json))
''',
        "start mode-bound permission",
    )


def main() -> int:
    patch_subscription_client()
    patch_live_identity()
    patch_runner_service()
    patch_dashboard_facade()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
