"""DashboardFacade —— QWebChannel 唯一注册对象（设计规格 §6.1）。

只读 + 配置往返面：Web 页面经此读写 Settings / _shell 外壳状态、查看运行方式
目录与预检结果。启动/停止入口（start_run/stop_run）按 task-3-brief 不在本阶段
白名单内，本类不提供。

行为规则（§6.3）：
- update_config 经 Settings._from_dict(patch, fallback=current) 清洗；任何
  非法字段（未知键 / PERSIST_DENYLIST / 类型被拒 / _shell 保留键）→ 整体拒绝、
  不落盘，errors 逐项回报。
- 保存 = collect_persistable_settings(s) + 现有 ``_shell`` 原样往返
  （防 ``_shell`` 孤儿化，审计风险 #3）；原子写。
"""

from __future__ import annotations

import json
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot

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
from shuabao.shell.runner_service import live_lock_busy
from shuabao.shell.runtime_status import RUNNER_IDLE
from shuabao.shell.runtime_status import runtime_status_from_mediator

THEMES = ("light", "dark")
DEFAULT_SHELL_THEME = "light"
DEFAULT_SHELL_MODE_ID = "normal_farm"
SHELL_BUNDLE_KEYS = frozenset({"_shell", "_shell_schema"})
PREFLIGHT_CHECK_IDS = ("mode_enabled", "live_lock", "skills_non_empty", "cycle_valid", "follow_pair_code")
SETTINGS_FIELD_NAMES = frozenset(f.name for f in dc_fields(Settings))


def _blocked_reason(mode_id: str) -> str:
    spec = get_spec(mode_id)
    if not spec.live_enabled:
        return f"{spec.label} 未开放 live"
    if not spec.desktop_start:
        return f"{spec.label} 未开放桌面入口"
    return ""


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
        on_minimize: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.app_data = Path(app_data)
        self._runner = runner
        self._on_minimize = on_minimize
        self._on_close = on_close
        self._path = user_settings_path(self.app_data)
        raw = self._read_bundle()
        self._shell: dict[str, Any] = dict(raw.get("_shell") or {})
        self._settings = Settings._from_dict(
            {k: v for k, v in raw.items() if k not in SHELL_BUNDLE_KEYS}
        )

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
                "enabled": bool(spec.live_enabled),
                "desktop_start": bool(spec.desktop_start),
                "evidence_status": spec.evidence_status,
                "badge": badge_text(spec),
                "blocked_reason": "" if startable else _blocked_reason(spec.id),
                "visible_settings": list(spec.visible_settings),
            })
        return out

    def _run_dto(self) -> dict[str, Any]:
        state = str(getattr(self._runner, "runner_state", "") or RUNNER_IDLE)
        mediator = getattr(getattr(self._runner, "worker", None), "mediator", None)
        phase = ""
        game_count = 0
        if mediator is not None and runtime_status_from_mediator is not None:
            try:
                status = runtime_status_from_mediator(mediator)
                phase = str(status.phase or "")
                game_count = int(getattr(mediator, "_game_count", 0) or 0)
            except Exception:
                pass
        return {
            "state": state,
            "mode_id": getattr(self._runner, "mode_id", None),
            "phase": phase,
            "game_count": game_count,
            "cycle_num": max(0, int(self._settings.cycle_num)),
            "terminal_reason": "",
            "ocr_status": "",
            "last_action": "",
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
        return json.dumps({
            "settings": collect_persistable_settings(self._settings),
            "shell": self._shell_dto(),
            "modes": self._modes_dto(),
            "run": self._run_dto(),
        }, ensure_ascii=False)

    @Slot(str, result=str)
    def update_config(self, patch_json: str) -> str:
        patch, err = self._parse_object(patch_json)
        if patch is None:
            return json.dumps({"ok": False, "errors": [err], "settings": {}}, ensure_ascii=False)

        errors: list[str] = []
        clean_patch: dict[str, Any] = {}
        for key, value in patch.items():
            if key in PERSIST_DENYLIST:
                errors.append(f"禁止修改字段: {key}")
            elif key in SHELL_BUNDLE_KEYS:
                errors.append(f"非法字段: {key}（外壳保留键不经 config 面改写）")
            else:
                clean_patch[key] = value

        cleaned = Settings._from_dict(clean_patch, fallback=self._settings)
        current = self._settings
        for key, value in clean_patch.items():
            if key not in SETTINGS_FIELD_NAMES:
                errors.append(f"未知字段: {key}")
                continue
            old, new = getattr(current, key), getattr(cleaned, key)
            if value != old and new == old:
                errors.append(f"字段值被清洗拒绝: {key}")

        if errors:
            # Fail-closed：任一非法字段 → 整体拒绝，不落盘。
            return json.dumps({
                "ok": False,
                "errors": errors,
                "settings": collect_persistable_settings(current),
            }, ensure_ascii=False)

        self._settings = cleaned
        self._persist()
        dto = collect_persistable_settings(self._settings)
        self.snapshot_changed.emit(self.get_snapshot())
        return json.dumps({"ok": True, "errors": [], "settings": dto}, ensure_ascii=False)

    @Slot(str, result=str)
    def update_shell(self, patch_json: str) -> str:
        patch, err = self._parse_object(patch_json)
        if patch is None:
            return json.dumps({"ok": False, "errors": [err], "shell": self._shell_dto()},
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
            return json.dumps({"ok": False, "errors": errors, "shell": self._shell_dto()},
                              ensure_ascii=False)

        self._shell.update(applied)
        self._persist()
        dto = self._shell_dto()
        self.snapshot_changed.emit(self.get_snapshot())
        return json.dumps({"ok": True, "errors": [], "shell": dto}, ensure_ascii=False)

    @Slot(result=str)
    def get_modes(self) -> str:
        return json.dumps(self._modes_dto(), ensure_ascii=False)

    @Slot(str, result=str)
    def validate_preflight(self, mode_id_json: str) -> str:
        mode_id = self._parse_keyed(mode_id_json, "mode_id")

        def check(cid: str, ok: bool, detail: str) -> dict[str, Any]:
            return {"id": cid, "ok": bool(ok), "detail": detail}

        specs = load_specs()
        if mode_id not in specs:
            checks = [check("mode_enabled", False, f"未知运行方式: {mode_id or '(空)'}")]
            return json.dumps({"ok": False, "blocked_reason": checks[0]["detail"],
                               "checks": checks}, ensure_ascii=False)

        settings = self._settings
        enabled = desktop_may_start(mode_id)
        lock_free = not live_lock_busy(self.app_data)
        skills = list(settings.skills or [])
        cycle_raw = settings.cycle_num
        cycle_ok = isinstance(cycle_raw, int) and not isinstance(cycle_raw, bool) and cycle_raw >= 0
        pair_code = settings.follow_pair_code or ""
        checks = [
            check("mode_enabled", enabled, "已验证可启动" if enabled else _blocked_reason(mode_id)),
            check("live_lock", lock_free, "live.lock 空闲" if lock_free else "live.lock 已被占用"),
            check("skills_non_empty", 1 <= len(skills) <= MAX_SELECTED_SKILLS,
                  f"技能 {len(skills)} 个" if skills else "技能为空"),
            check("cycle_valid", cycle_ok, f"循环次数 {cycle_raw}" if cycle_ok else f"循环次数非法: {cycle_raw!r}"),
            check("follow_pair_code", len(pair_code) <= 24,
                  f"配对码 {len(pair_code)} 字符" if len(pair_code) <= 24 else "配对码超过 24 字符"),
        ]
        first_fail = next((c["detail"] for c in checks if not c["ok"]), "")
        return json.dumps({"ok": all(c["ok"] for c in checks),
                           "blocked_reason": first_fail, "checks": checks},
                          ensure_ascii=False)

    @Slot(str, result=str)
    def window_control(self, action_json: str) -> str:
        action = self._parse_keyed(action_json, "action")
        handler = {"minimize": self._on_minimize, "close": self._on_close}.get(action)
        if handler is None:
            return json.dumps({"ok": False, "error": f"不支持的动作或无处理者: {action!r}"},
                              ensure_ascii=False)
        handler()
        return json.dumps({"ok": True})
