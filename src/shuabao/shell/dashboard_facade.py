"""DashboardFacade —— QWebChannel 唯一注册对象（设计规格 §6.1）。

只读 + 配置往返面 + 运行控制：Web 页面经此读写 Settings / _shell 外壳状态、
查看运行方式目录与预检结果，并通过 start_run / stop_run 驱动唯一 LIVE 入口
RunnerService（§6.3）。禁止直接触碰 api_server / runtime_mediator。

行为规则（§6.3）：
- update_config 经 Settings._from_dict(patch, fallback=current) 清洗；任何
  非法字段（未知键 / PERSIST_DENYLIST / 类型被拒 / _shell 保留键）→ 整体拒绝、
  不落盘，errors 逐项回报。
- 保存 = collect_persistable_settings(s) + 现有 ``_shell`` 原样往返
  （防 ``_shell`` 孤儿化，审计风险 #3）；原子写。
"""

from __future__ import annotations

import os
import json
import hashlib
import sys
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from shuabao.subscription_client import (
    SUBSCRIPTION_LICENSE_KEY_ENV,
    activate_device,
    check_start_permission,
    load_saved_license_key,
    save_license_key,
    validate_entitlement,
)

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from shuabao.paths import user_settings_path
from shuabao.settings import MAX_SELECTED_SKILLS, Settings
from shuabao.shell.mode_catalog import (
    PERSIST_DENYLIST,
    badge_text,
    collect_persistable_settings,
    desktop_may_start,
    get_spec,
    load_specs,
)
from shuabao.shell.runner_service import (
    RUNNER_COMPLETE,
    RUNNER_FAILED,
    RUNNER_IDLE,
    RUNNER_RUNNING,
    RUNNER_STARTING,
    RUNNER_STOPPING,
    RunnerService,
)
from shuabao.shell.runner_service import live_lock_busy
from shuabao.shell.runtime_status import runtime_status_from_mediator
from shuabao.shell.bridge_contract import (
    BRIDGE_REQUIRED_METHODS,
    BRIDGE_REQUIRED_SIGNALS,
    BRIDGE_SCHEMA_VERSION,
)
from shuabao.release_signing import (
    PINNED_MANIFEST_PUBLIC_KEYS,
    ReleaseManifestError,
    canonical_manifest_sha256,
    verify_packaged_release_snapshot,
)

THEMES = ("light", "dark")
DEFAULT_SHELL_THEME = "light"
DEFAULT_SHELL_MODE_ID = "normal_farm"
SHELL_BUNDLE_KEYS = frozenset({"_shell", "_shell_schema"})
PREFLIGHT_CHECK_IDS = (
    "mode_enabled",
    "live_lock",
    "skills_non_empty",
    "cycle_valid",
    "follow_pair_code",
    "subscription",
    "runtime_root",
    "ocr_runtime",
    "uipi",
    "target_window",
    "build_identity",
)
SETTINGS_REVISION_KEY = "_dashboard_settings_revision"


def _blocked_reason(mode_id: str) -> str:
    spec = get_spec(mode_id)
    if not spec.live_enabled:
        return f"{spec.label} 未开放 live"
    if not spec.desktop_start:
        return f"{spec.label} 未开放桌面入口"
    return ""


def _current_source_sha(root: Path | None) -> str:
    base = Path(root) if root is not None else Path.cwd()
    try:
        proc = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _build_identity_metadata(root: Path | None) -> dict[str, str]:
    """Read non-secret build identity fields for the dashboard evidence header."""
    base = Path(root) if root is not None else Path.cwd()
    candidates = [base]
    if getattr(sys, "executable", None):
        candidates.append(Path(sys.executable).resolve().parent)
    if base.parent not in candidates:
        candidates.append(base.parent)
    for candidate in candidates:
        identity_path = candidate / "build_identity.json"
        try:
            payload = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        metadata = {
            "source_sha": str(payload.get("source_sha") or "").strip(),
            "release_manifest_sha256": str(payload.get("release_manifest_sha256") or "").strip().lower(),
            "exe_sha256": str(payload.get("exe_sha256") or "").strip().lower(),
            "bridge_schema_version": str(payload.get("bridge_schema_version") or "").strip(),
            "ocr_model_sha256": str(payload.get("ocr_model_manifest_sha256") or "").strip().lower(),
        }
        manifest_path = identity_path.parent / "release_manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = None
            if isinstance(manifest, dict):
                if not metadata["release_manifest_sha256"]:
                    try:
                        metadata["release_manifest_sha256"] = canonical_manifest_sha256(manifest)
                    except (OSError, ReleaseManifestError):
                        pass
                if not metadata["bridge_schema_version"]:
                    metadata["bridge_schema_version"] = str(manifest.get("bridge_schema_version") or "")
                if not metadata["ocr_model_sha256"]:
                    for entry in manifest.get("files") or []:
                        if not isinstance(entry, dict):
                            continue
                        rel = str(entry.get("path") or "").replace("\\", "/")
                        if Path(rel).name.lower() == "model_manifest.json":
                            metadata["ocr_model_sha256"] = str(entry.get("sha256") or "").strip().lower()
                            break
        return metadata
    source_sha = _current_source_sha(base)
    return {"source_sha": source_sha} if source_sha else {}


def _evidence_path(base: Path, configured: Any, candidates: tuple[Path, ...]) -> Path | None:
    """Resolve an evidence artifact without trusting a stale display string."""
    raw = str(configured or "").strip()
    paths: list[Path] = []
    if raw:
        value = Path(raw)
        paths.append(value if value.is_absolute() else base / value)
    paths.extend(candidates)
    for path in paths:
        try:
            if path.is_file():
                return path.resolve()
        except (OSError, RuntimeError):
            continue
    return None


def _mode_evidence(mode_id: str, root: Path | None) -> dict[str, Any]:
    """Return current-build evidence without promoting historical evidence.

    A PASS record is accepted only when it carries the source/build bindings
    for the current checkout or frozen package.  Missing records are explicit
    and safe: they never disable a technical startable flag, but they do keep
    the dashboard's acceptance state honest.
    """
    base = Path(root) if root is not None else Path(__file__).resolve().parents[3]
    path = base / "config" / "mode_evidence.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "MISSING", "reason": "未找到当前构建证据清单"}
    modes = document.get("modes") if isinstance(document, dict) else None
    entry = modes.get(mode_id) if isinstance(modes, dict) else None
    if not isinstance(entry, dict):
        return {"status": "MISSING", "reason": "该运行方式未登记当前构建证据"}
    status = str(entry.get("status") or "MISSING").upper()
    if status not in {"PASS", "BLOCKED", "MISSING", "STALE"}:
        status = "MISSING"
    result = {
        "status": status,
        "reason": str(entry.get("reason") or ""),
        "source_sha": str(entry.get("source_sha") or ""),
        "release_manifest_sha256": str(entry.get("release_manifest_sha256") or ""),
        "exe_sha256": str(entry.get("exe_sha256") or ""),
        "bridge_schema_version": str(entry.get("bridge_schema_version") or ""),
        "ocr_model_sha256": str(entry.get("ocr_model_sha256") or ""),
        "scenario": str(entry.get("scenario") or ""),
        "captured_at": str(entry.get("captured_at") or ""),
        "evidence_bundle": str(entry.get("evidence_bundle") or ""),
        "postcondition": str(entry.get("postcondition") or ""),
    }
    build_identity = _build_identity_metadata(root)
    for key in ("source_sha", "release_manifest_sha256", "exe_sha256", "bridge_schema_version", "ocr_model_sha256"):
        if not result[key] and build_identity.get(key):
            result[key] = build_identity[key]
    current_source = _current_source_sha(base)
    if result["status"] == "PASS":
        if not result["source_sha"] or (current_source and result["source_sha"] != current_source):
            result["status"] = "STALE"
            result["reason"] = "PASS 证据未绑定当前源码 SHA"
        elif not result["release_manifest_sha256"] or not result["exe_sha256"]:
            result["status"] = "STALE"
            result["reason"] = "PASS 证据缺少发行清单或 EXE 哈希"
        else:
            package_candidates = (
                base / "dist" / "ShuaBao" / "release_manifest.json",
                base / "web" / "release_manifest.json",
                base / "release_manifest.json",
            )
            manifest_path = _evidence_path(base, entry.get("release_manifest_path"), package_candidates)
            if manifest_path is None:
                result["status"] = "STALE"
                result["reason"] = "PASS 证据未提供可读取的发行清单"
            else:
                result["release_manifest_path"] = str(manifest_path)
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest_hash = canonical_manifest_sha256(manifest)
                except (OSError, ValueError, ReleaseManifestError):
                    manifest_hash = ""
                    manifest = None
                manifest_valid = False
                if manifest_hash != result["release_manifest_sha256"].lower():
                    result["status"] = "STALE"
                    result["reason"] = "PASS 证据的发行清单哈希不匹配"
                else:
                    try:
                        manifest_bridge_schema = int(manifest.get("bridge_schema_version", -1)) if isinstance(manifest, dict) else -1
                    except (TypeError, ValueError):
                        manifest_bridge_schema = -1
                    manifest_valid = (
                        isinstance(manifest, dict)
                        and manifest.get("schema_version") == 1
                        and manifest.get("source_sha") == result["source_sha"]
                        and manifest_bridge_schema == BRIDGE_SCHEMA_VERSION
                        and isinstance(manifest.get("files"), list)
                        and bool(manifest.get("files"))
                    )
                if manifest_hash == result["release_manifest_sha256"].lower() and not manifest_valid:
                    result["status"] = "STALE"
                    result["reason"] = "PASS 证据的发行清单内容不完整或未绑定相同源码 SHA"
                elif manifest_hash == result["release_manifest_sha256"].lower() and manifest_valid:
                    exe_name = str(entry.get("exe_name") or "ShuaBao.exe").strip() or "ShuaBao.exe"
                    exe_candidates = (
                        manifest_path.parent / exe_name,
                        manifest_path.parent / "ShuaBao.exe",
                    )
                    exe_path = _evidence_path(base, entry.get("exe_path"), exe_candidates)
                    if exe_path is None:
                        result["status"] = "STALE"
                        result["reason"] = "PASS 证据未提供可读取的 EXE"
                    else:
                        result["exe_path"] = str(exe_path)
                        try:
                            exe_hash = hashlib.sha256(exe_path.read_bytes()).hexdigest().lower()
                        except OSError:
                            exe_hash = ""
                        if exe_hash != result["exe_sha256"].lower():
                            result["status"] = "STALE"
                            result["reason"] = "PASS 证据的 EXE 哈希不匹配"
    return result


def _production_runtime_context(root: Path | None, runner: Any) -> bool:
    """Whether optional host checks can be evaluated locally.

    Unit tests and browser mocks intentionally inject a fake runner or omit a
    repository root.  The real desktop/WebShell path always supplies a
    RunnerService plus either the source entry point or a frozen bundle.
    """
    if not isinstance(runner, RunnerService):
        return False
    if getattr(sys, "frozen", False):
        return True
    return bool(root is not None and (Path(root) / "desktop_app.py").is_file())


def _ocr_preflight(settings: Settings, root: Path | None, runner: Any) -> tuple[bool, str]:
    mode = str(getattr(settings, "ocr_mode", "off") or "off").lower()
    if mode not in {"off", "shadow", "live"}:
        return False, f"ocr_mode 非法: {mode}"
    if mode == "off":
        return True, "OCR 已关闭（模板模式）"
    if not _production_runtime_context(root, runner):
        return True, "OCR 由启动 worker 负责校验"
    base = Path(root) if root is not None else Path.cwd()
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        worker = exe_dir / "vision" / "ShuaBaoOCR.exe"
        model_candidates = (
            exe_dir / "vision" / "models" / "ocr" / "MODEL_MANIFEST.json",
            exe_dir / "vision" / "_internal" / "models" / "ocr" / "MODEL_MANIFEST.json",
            exe_dir / "models" / "ocr" / "MODEL_MANIFEST.json",
        )
        model_manifest = next((path for path in model_candidates if path.is_file()), model_candidates[0])
    else:
        explicit = str(os.environ.get("SHUABAO_OCR_PYTHON") or "").strip()
        worker = Path(explicit) if explicit else base / ".venv-ocr" / "Scripts" / "python.exe"
        model_manifest = base / "models" / "ocr" / "MODEL_MANIFEST.json"
    if not worker.is_file():
        return False, f"OCR worker 不存在: {worker}"
    if not model_manifest.is_file():
        return False, f"OCR 模型清单不存在: {model_manifest}"
    return True, "OCR worker 与模型清单可用"


def _uipi_preflight(settings: Settings, root: Path | None, runner: Any) -> tuple[bool, str]:
    if bool(getattr(settings, "dry_run", False)):
        return True, "学习模式不需要 UIPI 提权"
    if not _production_runtime_context(root, runner) or os.name != "nt":
        return True, "由启动器/运行环境负责 UIPI 校验"
    try:
        from shuabao.input.keyboard_mouse import is_current_process_elevated

        elevated = bool(is_current_process_elevated())
    except Exception:
        elevated = False
    return (elevated, "当前进程已提权" if elevated else "当前进程未提权，真实输入会被 UIPI 丢弃")


def _target_window_preflight(
    settings: Settings,
    mode_id: str,
    root: Path | None,
    runner: Any,
) -> tuple[bool, str]:
    """Confirm that a usable KK/game window exists before LIVE input.

    A fresh solo run may legitimately begin in the KK lobby, so normal_farm
    accepts either the game window or the platform window.  Team/follow modes
    start from the lobby and therefore require the L0 target.  Tests and dry
    runs intentionally defer this host-only probe.
    """
    if bool(getattr(settings, "dry_run", False)):
        return True, "学习模式不需要目标窗口"
    if not _production_runtime_context(root, runner) or os.name != "nt":
        return True, "由启动 worker 负责目标窗口校验"
    try:
        from shuabao.vision.capture import find_window_targets

        l1_title = str(getattr(settings, "window_title_contains", "") or "英雄三国")
        roles = ("l0",) if mode_id in {"follow_team", "lobby_hitch"} else ("l1", "l0")
        targets = []
        for role in roles:
            # Empty L0 query intentionally selects capture.py's verified KK
            # fallback vocabulary and role scoring.  Reusing the L1 title here
            # made a clean “KK lobby only” start fail preflight.
            title = l1_title if role == "l1" else ""
            targets.extend(find_window_targets(title, role=role, allow_fallback=False))
        if targets:
            names = ", ".join(str(getattr(item, "title", "") or "KK") for item in targets[:2])
            return True, f"目标窗口可用: {names}"
        return False, "未找到可用的 KK/英雄三国目标窗口"
    except Exception as exc:
        return False, f"目标窗口探测失败: {type(exc).__name__}"


def _build_identity_preflight(root: Path | None, runner: Any) -> tuple[bool, str]:
    if not _production_runtime_context(root, runner):
        return True, "源码/测试模式由构建入口负责身份校验"
    if not getattr(sys, "frozen", False):
        # Source mode is intentionally runnable before a packaging pass.
        return True, "源码模式使用当前 checkout；冻结包需提供签名发行快照"
    base = Path(root) if root is not None else Path.cwd()
    exe_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "executable", None)
        else base
    )
    candidates = [base, exe_dir]
    if base.parent not in candidates:
        candidates.append(base.parent)
    package_root = next(
        (candidate for candidate in candidates if (candidate / "release_manifest.json").is_file()),
        exe_dir,
    )
    try:
        manifest, verified_files, _manifest_bytes = verify_packaged_release_snapshot(
            package_root,
            pinned_keys=PINNED_MANIFEST_PUBLIC_KEYS,
            required_files=("config/entitlement_public_keys.json",),
        )
    except (OSError, ValueError, ReleaseManifestError) as exc:
        if isinstance(exc, ReleaseManifestError):
            return False, f"发行快照校验失败: {exc.code}: {exc.message}"
        return False, f"发行快照校验失败: {type(exc).__name__}: {exc}"
    source_value = manifest.get("source_sha")
    channel_value = manifest.get("release_channel")
    source_sha = source_value.strip() if isinstance(source_value, str) else ""
    release_channel = channel_value.strip() if isinstance(channel_value, str) else ""
    try:
        bridge_schema = int(manifest.get("bridge_schema_version", -1))
    except (TypeError, ValueError):
        bridge_schema = -1
    if not source_sha or not release_channel:
        return False, "签名发行清单缺少 source_sha/release_channel"
    if bridge_schema != BRIDGE_SCHEMA_VERSION:
        return False, f"签名发行清单 bridge_schema 不一致: {bridge_schema}"
    exe_path = Path(sys.executable).resolve() if getattr(sys, "executable", None) else None
    try:
        exe_relative = exe_path.relative_to(package_root.resolve()).as_posix() if exe_path else ""
    except ValueError:
        exe_relative = ""
    exe_name = Path(exe_relative).name if exe_relative else "ShuaBao.exe"
    exe_sha = ""
    ocr_model_sha = ""
    for relative, data in verified_files.items():
        if relative.lower() == exe_relative.lower():
            exe_sha = hashlib.sha256(data).hexdigest().lower()
        if Path(relative).name.lower() == "model_manifest.json":
            ocr_model_sha = hashlib.sha256(data).hexdigest().lower()
    if not exe_sha:
        return False, f"签名发行清单未绑定 EXE: {exe_name}"
    if not ocr_model_sha:
        return False, "签名发行清单缺少 OCR 模型清单哈希"
    return True, (
        f"source_sha={source_sha}; release_channel={release_channel}; "
        f"manifest_sha256={canonical_manifest_sha256(manifest)}; "
        f"exe_sha256={exe_sha}; bridge_schema={bridge_schema}; "
        f"ocr_model_sha256={ocr_model_sha}"
    )


class DashboardFacade(QObject):
    """规格 §6.1 白名单方法面。入参出参均为 JSON 字符串。"""

    snapshot_changed = Signal(str)
    run_status_changed = Signal(str)
    log_appended = Signal(str, str)

    def __init__(
        self,
        app_data: Path,
        runner: Any = None,
        *,
        root: Path | None = None,
        on_minimize: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
        on_layout: Callable[[str], None] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.app_data = Path(app_data)
        self._runner = runner
        self._on_minimize = on_minimize
        self._on_close = on_close
        self._on_layout = on_layout
        self._root = Path(root) if root is not None else None
        # §6.3 运行态轮询：与原生 _poll_runtime 同模式，400ms 读 mediator 快照。
        self._poll = QTimer(self)
        self._poll.setInterval(400)
        self._poll.timeout.connect(self._poll_runtime)
        self._last_run_json = ""
        self._path = user_settings_path(self.app_data)
        # 20260831 审查（P2）：显式注入的 env key 优先级高于磁盘 saved key，
        # 只在 env 为空时才回填，避免覆盖启动器/上层会话已设定的授权。
        saved_key = load_saved_license_key(self.app_data)
        if saved_key and not os.environ.get(SUBSCRIPTION_LICENSE_KEY_ENV, "").strip():
            os.environ[SUBSCRIPTION_LICENSE_KEY_ENV] = saved_key
        raw = self._read_bundle()
        self._shell: dict[str, Any] = dict(raw.get("_shell") or {})
        self._settings = Settings._from_dict(
            {k: v for k, v in raw.items() if k not in SHELL_BUNDLE_KEYS}
        )
        revision = raw.get(SETTINGS_REVISION_KEY, 0)
        self._settings_revision = revision if type(revision) is int and revision >= 0 else 0
        self._snapshot_seq = 0
        # Subscription probes are bounded and cached.  Snapshot reads happen
        # on the QWebChannel GUI thread; never perform a network request merely
        # because the header/status DTO is being painted.
        self._subscription_cache_key: tuple[str, str, str, str] | None = None
        self._subscription_cache_at = 0.0
        self._subscription_cache: Any = None
        self._subscription_cache_ttl_s = 15.0

    def _ensure_runner(self) -> Any:
        """注入的 runner 优先；否则按缺省构造 RunnerService(app_data, root)。"""
        if self._runner is None:
            if self._root is None:
                return None
            self._runner = RunnerService(self.app_data, self._root)
        return self._runner

    # ------------------------------------------------------------- 内部工具

    def _read_bundle(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _persist(self) -> None:
        data = collect_persistable_settings(self._settings)
        data["_shell"] = dict(self._shell)
        # ponytail: 延迟导入原生看板的 schema 版本，单测不必拉起整个 main_window。
        try:
            from shuabao.shell.main_window import SHELL_SCHEMA_VERSION
        except Exception:
            SHELL_SCHEMA_VERSION = 2
        data[SETTINGS_REVISION_KEY] = self._settings_revision
        data["_shell_schema"] = int(SHELL_SCHEMA_VERSION)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def _shell_dto(self) -> dict[str, Any]:
        theme = self._shell.get("theme")
        mode_id = self._shell.get("selected_mode_id")
        if theme not in THEMES:
            theme = DEFAULT_SHELL_THEME
        if not isinstance(mode_id, str) or mode_id not in load_specs():
            mode_id = DEFAULT_SHELL_MODE_ID
        return {"theme": theme, "selected_mode_id": mode_id}

    def _modes_dto(self) -> list[dict[str, Any]]:
        out = []
        for spec in load_specs().values():
            startable = desktop_may_start(spec.id)
            out.append({
                "id": spec.id,
                "label": spec.label,
                "startable": startable,
                "evidence_status": spec.evidence_status,
                "current_evidence": _mode_evidence(spec.id, self._root),
                "badge": badge_text(spec),
                "blocked_reason": "" if startable else _blocked_reason(spec.id),
                "visible_settings": list(spec.visible_settings),
            })
        return out

    def _strategy_dto(self) -> dict[str, Any]:
        return {
            "skills": list(self._settings.skills),
            "bonds": list(self._settings.bonds),
            "cards": list(self._settings.cards),
            "attributes": list(self._settings.attributes),
            "merchant": {
                "enabled": self._settings.merchant_enabled,
                "max_rerolls": self._settings.merchant_max_rerolls,
                "gold_reserve": self._settings.merchant_gold_reserve,
            },
            "treasure": {"negative_allowlist": list(self._settings.treasure_allow_negative)},
        }

    def _subscription_key(self) -> tuple[str, str, str, str]:
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

    def _invalidate_subscription_cache(self) -> None:
        self._subscription_cache_key = None
        self._subscription_cache_at = 0.0
        self._subscription_cache = None

    def _subscription_dto(self) -> dict[str, Any]:
        key = str(os.environ.get(SUBSCRIPTION_LICENSE_KEY_ENV) or "").strip()
        if not key:
            return {"active": False, "status": "未激活", "expires_at": ""}
        permission = self._subscription_cache
        if permission is None or self._subscription_cache_key != self._subscription_key():
            return {"active": False, "status": "待校验", "expires_at": ""}
        return {
            "active": bool(permission.allowed and permission.would_allow is not False),
            "status": str(permission.status or ("正常" if permission.allowed else "未激活")),
            "expires_at": str(getattr(permission, "expires_at", "") or ""),
        }

    def _snapshot_dto(self, request_id: str | None = None) -> dict[str, Any]:
        self._snapshot_seq += 1
        return {
            "request_id": request_id,
            "settings_revision": self._settings_revision,
            "snapshot_seq": self._snapshot_seq,
            "settings": collect_persistable_settings(self._settings),
            "strategy": self._strategy_dto(),
            "shell": self._shell_dto(),
            "modes": self._modes_dto(),
            "run": self._run_dto(),
            "subscription": self._subscription_dto(),
        }

    def _rpc_response(self, ok: bool, request_id: str | None = None, **body: Any) -> dict[str, Any]:
        return {
            "ok": ok,
            "request_id": request_id,
            "settings_revision": self._settings_revision,
            "snapshot_seq": self._snapshot_seq,
            **body,
        }

    def _run_dto(self) -> dict[str, Any]:
        runner = self._runner
        worker = getattr(runner, "worker", None)
        state = str(getattr(runner, "runner_state", "") or RUNNER_IDLE)
        mediator = getattr(worker, "mediator", None)
        phase = ""
        game_count = 0
        if mediator is not None and runtime_status_from_mediator is not None:
            try:
                status = runtime_status_from_mediator(mediator)
                phase = str(status.phase or "")
                game_count = int(getattr(mediator, "_game_count", 0) or 0)
            except Exception:
                pass
        started_settings = None
        getter = getattr(runner, "started_settings", None)
        if callable(getter):
            try:
                started_settings = getter()
            except Exception:
                started_settings = None
        if started_settings is None:
            started_settings = getattr(runner, "_started_settings", None)
        run_settings = started_settings or self._settings
        # mediator 未挂载时退回 worker 记录值（与原生 update_status 同语义）。
        return {
            "state": state,
            "mode_id": getattr(runner, "mode_id", None),
            "phase": phase or str(getattr(worker, "phase", "") or ""),
            "game_count": game_count,
            "cycle_num": max(0, int(getattr(run_settings, "cycle_num", 0) or 0)),
            "terminal_reason": str(getattr(worker, "terminal_reason", "") or ""),
            "ocr_status": str(getattr(worker, "ocr_status", "") or ""),
            "last_action": str(getattr(worker, "last_action", "") or ""),
        }

    @staticmethod
    def _parse_object(payload: str) -> tuple[dict[str, Any] | None, str | None]:
        """JSON 字符串 → dict。非对象返回 (None, 错误说明)。"""
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            return None, "payload 不是合法 JSON"
        if not isinstance(data, dict):
            return None, "payload 必须是 JSON 对象"
        return data, None

    @staticmethod
    def _parse_keyed(payload: str, key: str) -> str | None:
        """接受裸字符串或 {key: ...} 两种形态；解析不出返回空串（fail-closed）。"""
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            data = payload
        if isinstance(data, dict):
            data = data.get(key)
        return data if isinstance(data, str) else ""

    # ------------------------------------------------------------- 白名单 Slot

    @Slot(result=str)
    def get_snapshot(self) -> str:
        return json.dumps(self._snapshot_dto(), ensure_ascii=False)

    @Slot(result=str)
    def get_bridge_info(self) -> str:
        """Return the version handshake required before a Web bundle starts."""
        return json.dumps(
            {
                "ok": True,
                "schema_version": BRIDGE_SCHEMA_VERSION,
                "required_methods": list(BRIDGE_REQUIRED_METHODS),
                "required_signals": list(BRIDGE_REQUIRED_SIGNALS),
            },
            ensure_ascii=False,
        )

    @Slot(str, result=str)
    def update_config(self, patch_json: str) -> str:
        patch, err = self._parse_object(patch_json)
        if patch is None:
            return json.dumps(self._rpc_response(False, errors=[err], settings={}, strategy={}), ensure_ascii=False)

        request_id = patch.pop("request_id", None)
        expected_revision = patch.pop("settings_revision", None)
        errors: list[str] = []
        if request_id is not None and (type(request_id) is not str or not request_id):
            errors.append("request_id 必须为非空 string")
        if expected_revision is not None:
            if type(expected_revision) is not int:
                errors.append("settings_revision 必须为 int")
            elif expected_revision != self._settings_revision:
                errors.append("settings_revision 已过期")

        strategy = patch.pop("strategy", None)
        if strategy is not None:
            if type(strategy) is not dict:
                errors.append("strategy 必须为 object")
            else:
                mappings = {
                    "skills": "skills",
                    "bonds": "bonds",
                    "attributes": "attributes",
                    "merchant": {
                        "enabled": "merchant_enabled",
                        "max_rerolls": "merchant_max_rerolls",
                        "gold_reserve": "merchant_gold_reserve",
                    },
                    "treasure": {"negative_allowlist": "treasure_allow_negative"},
                }
                for key, value in strategy.items():
                    target = mappings.get(key)
                    if target is None:
                        errors.append(f"strategy 未知字段: {key}")
                    elif isinstance(target, str):
                        if target in patch:
                            errors.append(f"strategy 与顶层字段重复: {target}")
                        else:
                            patch[target] = value
                    elif type(value) is not dict:
                        errors.append(f"strategy.{key} 必须为 object")
                    else:
                        unknown = set(value) - set(target)
                        errors.extend(f"strategy.{key} 未知字段: {name}" for name in sorted(unknown))
                        for nested_key, nested_value in value.items():
                            mapped = target.get(nested_key)
                            if mapped is not None:
                                if mapped in patch:
                                    errors.append(f"strategy 与顶层字段重复: {mapped}")
                                else:
                                    patch[mapped] = nested_value

        for key in patch:
            if key in PERSIST_DENYLIST:
                errors.append(f"禁止修改字段: {key}")
            elif key in SHELL_BUNDLE_KEYS or key == SETTINGS_REVISION_KEY:
                errors.append(f"非法字段: {key}")
        errors.extend(Settings.validate_patch(patch, self._settings))
        if errors:
            return json.dumps(self._rpc_response(
                False, request_id if type(request_id) is str else None, errors=errors,
                settings=collect_persistable_settings(self._settings), strategy=self._strategy_dto(),
            ), ensure_ascii=False)

        self._settings = Settings._from_dict(patch, fallback=self._settings)
        self._settings_revision += 1
        self._persist()
        snapshot = self._snapshot_dto(request_id if type(request_id) is str else None)
        self.snapshot_changed.emit(json.dumps(snapshot, ensure_ascii=False))
        return json.dumps(self._rpc_response(
            True, request_id if type(request_id) is str else None, errors=[],
            settings=collect_persistable_settings(self._settings), strategy=self._strategy_dto(),
        ), ensure_ascii=False)

    @Slot(str, result=str)
    def update_shell(self, patch_json: str) -> str:
        patch, err = self._parse_object(patch_json)
        if patch is None:
            return json.dumps(self._rpc_response(False, errors=[err], shell=self._shell_dto()),
                              ensure_ascii=False)

        errors: list[str] = []
        applied: dict[str, Any] = {}
        if "theme" in patch:
            theme = patch["theme"]
            if theme in THEMES:
                applied["theme"] = theme
            else:
                errors.append(f"theme 取值非法: {theme!r}")
        if "selected_mode_id" in patch:
            mode_id = patch["selected_mode_id"]
            if isinstance(mode_id, str) and mode_id in load_specs():
                applied["selected_mode_id"] = mode_id
            else:
                errors.append(f"selected_mode_id 未知: {mode_id!r}")
        unknown = set(patch) - {"theme", "selected_mode_id"}
        for key in sorted(unknown):
            errors.append(f"update_shell 仅接受 theme/selected_mode_id，收到: {key}")

        if errors:
            return json.dumps(self._rpc_response(False, errors=errors, shell=self._shell_dto()),
                              ensure_ascii=False)

        self._shell.update(applied)
        self._persist()
        dto = self._shell_dto()
        self.snapshot_changed.emit(json.dumps(self._snapshot_dto(), ensure_ascii=False))
        return json.dumps(self._rpc_response(True, errors=[], shell=dto), ensure_ascii=False)

    @Slot(str, result=str)
    def validate_preflight(self, mode_id_json: str) -> str:
        mode_id = self._parse_keyed(mode_id_json, "mode_id")

        def check(cid: str, ok: bool, detail: str) -> dict[str, Any]:
            return {"id": cid, "ok": bool(ok), "detail": detail}

        specs = load_specs()
        if mode_id not in specs:
            checks = [check("mode_enabled", False, f"未知运行方式: {mode_id or '(空)'}")]
            return json.dumps(self._rpc_response(
                False, blocked_reason=checks[0]["detail"], checks=checks,
            ), ensure_ascii=False)

        settings = self._settings
        enabled = desktop_may_start(mode_id)
        lock_free = not live_lock_busy(self.app_data)
        skills = list(settings.skills or [])
        cycle_raw = (
            settings.follow_cycle_num
            if mode_id == "follow_team"
            else settings.hitch_cycle_num
            if mode_id == "lobby_hitch"
            else settings.cycle_num
        )
        cycle_ok = isinstance(cycle_raw, int) and not isinstance(cycle_raw, bool) and cycle_raw >= 0
        pair_code = settings.follow_pair_code or ""
        permission = self._subscription_permission()
        runtime_root_ok = self._root is None or Path(self._root).is_dir() or self._runner is not None
        runtime_root_detail = (
            "运行目录可用"
            if runtime_root_ok and self._root is not None
            else "由注入的 RunnerService 提供运行目录"
            if self._runner is not None
            else "启动时解析运行目录"
        )
        ocr_ok, ocr_detail = _ocr_preflight(settings, self._root, self._runner)
        uipi_ok, uipi_detail = _uipi_preflight(settings, self._root, self._runner)
        window_ok, window_detail = _target_window_preflight(
            settings, mode_id, self._root, self._runner
        )
        identity_ok, identity_detail = _build_identity_preflight(self._root, self._runner)
        checks = [
            check("mode_enabled", enabled, "已验证可启动" if enabled else _blocked_reason(mode_id)),
            check("live_lock", lock_free, "live.lock 空闲" if lock_free else "live.lock 已被占用"),
            check("skills_non_empty", 1 <= len(skills) <= MAX_SELECTED_SKILLS,
                  f"技能 {len(skills)} 个" if skills else "技能为空"),
            check("cycle_valid", cycle_ok, f"循环次数 {cycle_raw}" if cycle_ok else f"循环次数非法: {cycle_raw!r}"),
            check("follow_pair_code", len(pair_code) <= 24,
                  f"配对码 {len(pair_code)} 字符" if len(pair_code) <= 24 else "配对码超过 24 字符"),
            check(
                "subscription",
                bool(permission.allowed),
                permission.message or f"订阅状态 {permission.status}",
            ),
            check(
                "runtime_root",
                runtime_root_ok,
                runtime_root_detail if runtime_root_ok else "运行目录不可用，无法创建 LIVE worker",
            ),
            check("ocr_runtime", ocr_ok, ocr_detail),
            check("uipi", uipi_ok, uipi_detail),
            check("target_window", window_ok, window_detail),
            check("build_identity", identity_ok, identity_detail),
        ]
        first_fail = next((c["detail"] for c in checks if not c["ok"]), "")
        return json.dumps(self._rpc_response(
            all(c["ok"] for c in checks), blocked_reason=first_fail, checks=checks,
        ), ensure_ascii=False)

    @Slot(str, result=str)
    def window_control(self, action_json: str) -> str:
        action = self._parse_keyed(action_json, "action")
        handler = {"minimize": self._on_minimize, "close": self._on_close}.get(action)
        if handler is None:
            return json.dumps(self._rpc_response(
                False, error=f"不支持的动作或无处理者: {action!r}",
            ), ensure_ascii=False)
        handler()
        return json.dumps(self._rpc_response(True))

    @Slot(str, result=str)
    def set_window_layout(self, layout_json: str) -> str:
        """页面切换时只调整宿主尺寸；不写入用户配置。"""
        layout = self._parse_keyed(layout_json, "layout")
        if layout not in {"dashboard", "chooser", "chooser-solo", "chooser-team"} or self._on_layout is None:
            return json.dumps(self._rpc_response(False, error=f"不支持的布局: {layout!r}"), ensure_ascii=False)
        self._on_layout(layout)
        return json.dumps(self._rpc_response(True), ensure_ascii=False)

    # ------------------------------------------------------------- 运行控制（§6.3）

    @Slot(str, result=str)
    def start_run(self, mode_id_json: str) -> str:
        """先刷新一次授权，随后 preflight 复用该结果并将同一对象传入 RunnerService。"""
        permission = self._subscription_permission(force=True)
        pre = json.loads(self.validate_preflight(mode_id_json))
        if not pre["ok"]:
            return json.dumps(self._rpc_response(False, error=pre["blocked_reason"]),
                              ensure_ascii=False)
        if not permission.allowed:
            return json.dumps(self._rpc_response(
                False, error=permission.message or "订阅未授权，无法启动",
            ), ensure_ascii=False)
        payload: dict[str, Any]
        if isinstance(mode_id_json, str) and mode_id_json.strip().startswith("{"):
            try:
                decoded = json.loads(mode_id_json)
            except (TypeError, ValueError):
                decoded = {}
            payload = decoded if isinstance(decoded, dict) else {}
        else:
            # The bridge normally sends {mode_id, expected_settings_revision},
            # but accepting a bare JSON string remains part of the Slot's
            # compatibility contract.  Do not pass the quoted wire payload
            # through to RunnerService as a mode identifier.
            payload = {"mode_id": self._parse_keyed(mode_id_json, "mode_id")}
        expected_rev = payload.get("expected_settings_revision")
        if expected_rev is not None:
            if type(expected_rev) is not int:
                return json.dumps(self._rpc_response(False, error="expected_settings_revision 必须为 int"), ensure_ascii=False)
            if expected_rev != self._settings_revision:
                return json.dumps(self._rpc_response(False, error=f"Settings revision mismatch: expected {expected_rev}, current {self._settings_revision}"), ensure_ascii=False)
        mode_id = payload.get("mode_id") or self._parse_keyed(mode_id_json, "mode_id")
        runner = self._ensure_runner()
        if runner is None:
            return json.dumps(self._rpc_response(
                False, error="未注入 RunnerService 且缺少 root，无法启动",
            ), ensure_ascii=False)
        try:
            worker = runner.start(mode_id, self._settings, permission=permission)
        except Exception as exc:  # ModeNotEnabled / already running / live.lock 占用
            return json.dumps(self._rpc_response(False, error=str(exc)), ensure_ascii=False)
        # Worker 在自身线程发信号；QueuedConnection 保证 Facade 侧在主线程收。
        worker.signals.log_emitted.connect(self.log_appended, Qt.QueuedConnection)
        worker.signals.status_updated.connect(self._on_status_updated,
                                              Qt.QueuedConnection)
        worker.finished.connect(self._on_worker_finished, Qt.QueuedConnection)
        worker.start()
        self._last_run_json = ""  # 强制下一次状态回传
        self._poll.start()
        return json.dumps(self._rpc_response(True), ensure_ascii=False)

    @Slot(result=str)
    def stop_run(self) -> str:
        """一律进入 runner.stop()（§6.3），不提前宣布已停止。"""
        runner = self._ensure_runner()
        if runner is None:
            return json.dumps(self._rpc_response(False, error="没有可停止的运行"),
                              ensure_ascii=False)
        try:
            runner.stop()
        except Exception as exc:
            return json.dumps(self._rpc_response(False, error=str(exc)), ensure_ascii=False)
        return json.dumps(self._rpc_response(True), ensure_ascii=False)
    @Slot(str, result=str)
    def activate_subscription(self, key_json: str) -> str:
        key = self._parse_keyed(key_json, "key") or ""
        key = key.strip()
        if not key:
            return json.dumps(self._rpc_response(False, message="卡密不能为空"), ensure_ascii=False)
        try:
            act = activate_device(key)
            if not act.get("ok"):
                err = str(act.get("message") or act.get("error") or "设备激活失败")
                return json.dumps(self._rpc_response(False, message=err), ensure_ascii=False)
            val = validate_entitlement(key)
            valid = bool(val.get("valid")) and val.get("can_start_runner") is True
            status = str(val.get("status") or ("正常" if valid else "未激活"))
            expires_at = str(val.get("expires_at") or "")
            if valid:
                # 20260831 审查（P2）：先落盘后写 env。DPAPI 保存失败时不得
                # 留下"UI 报保存失败但本会话仍可运行"的不一致授权状态。
                if not save_license_key(self.app_data, key):
                    return json.dumps(self._rpc_response(False, message="卡密验证成功，但本机保存失败"), ensure_ascii=False)
                os.environ[SUBSCRIPTION_LICENSE_KEY_ENV] = key
            self._invalidate_subscription_cache()
            # Keep the just-validated result visible without making the next
            # snapshot perform another network request.  ``check_start_permission``
            # will re-probe when the user starts a run or the TTL expires.
            if valid:
                from shuabao.subscription_client import StartPermission

                self._subscription_cache_key = self._subscription_key()
                self._subscription_cache_at = time.monotonic()
                self._subscription_cache = StartPermission(
                    True,
                    str(os.environ.get("SHUABAO_SUBSCRIPTION_MODE") or "enforce"),
                    status=status,
                    code=str(val.get("code") or ""),
                    message=str(val.get("message") or ""),
                    would_allow=True,
                    expires_at=expires_at,
                )
            sub = {"active": valid, "status": status, "expires_at": expires_at}
            self.snapshot_changed.emit(json.dumps(self._snapshot_dto(), ensure_ascii=False))
            return json.dumps(self._rpc_response(
                valid,
                subscription=sub,
                status=status,
                expires_at=expires_at,
                message=f"激活成功！到期时间: {expires_at[:10] if len(expires_at)>=10 else expires_at}" if valid else f"状态: {status}",
            ), ensure_ascii=False)
        except Exception as exc:
            return json.dumps(self._rpc_response(False, message=f"激活异常: {exc}"), ensure_ascii=False)


    def _on_status_updated(self, running: bool, phase: str, game_count: int,
                           terminal_reason: str, ocr_status: str,
                           last_action: str) -> None:
        if running:
            state = RUNNER_RUNNING
        else:
            state = RUNNER_FAILED if str(phase or "").upper() == "ERROR" else RUNNER_COMPLETE
        runner_state = str(getattr(self._runner, "runner_state", "") or state)
        # A queued terminal signal can arrive just before RunnerService handles
        # QThread.finished.  Do not let the stale RUNNING/STOPPING value hide
        # the terminal outcome in that small ordering window.
        if not running and runner_state in {RUNNER_RUNNING, RUNNER_STARTING, RUNNER_STOPPING, RUNNER_IDLE}:
            runner_state = state
        started_settings = None
        getter = getattr(self._runner, "started_settings", None)
        if callable(getter):
            try:
                started_settings = getter()
            except Exception:
                started_settings = None
        if started_settings is None:
            started_settings = getattr(self._runner, "_started_settings", None)
        run_settings = started_settings or self._settings
        dto = {
            "state": runner_state,
            "mode_id": getattr(self._runner, "mode_id", None),
            "phase": str(phase or ""),
            "game_count": max(0, int(game_count or 0)),
            "cycle_num": max(0, int(getattr(run_settings, "cycle_num", 0) or 0)),
            "terminal_reason": str(terminal_reason or ""),
            "ocr_status": str(ocr_status or ""),
            "last_action": str(last_action or ""),
        }
        payload = json.dumps(dto, ensure_ascii=False)
        if payload != self._last_run_json:
            self._last_run_json = payload
            self.run_status_changed.emit(payload)

    def _poll_runtime(self) -> None:
        payload = json.dumps(self._run_dto(), ensure_ascii=False)
        if payload != self._last_run_json:
            self._last_run_json = payload
            self.run_status_changed.emit(payload)
        worker = getattr(self._runner, "worker", None)
        if worker is None or not worker.isRunning():
            self._poll.stop()

    def _on_worker_finished(self) -> None:
        runner = getattr(self._runner, "release_after_finish", None)
        if callable(runner):
            try:
                self._runner.release_after_finish()
            except Exception:
                pass
        self._poll.stop()
        self._last_run_json = ""
        self.run_status_changed.emit(json.dumps(self._run_dto(), ensure_ascii=False))
