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

import json
from pathlib import Path
from typing import Any, Callable

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
from shuabao.shell.runner_service import RUNNER_IDLE, RUNNER_RUNNING, RunnerService
from shuabao.shell.runner_service import live_lock_busy
from shuabao.shell.runtime_status import runtime_status_from_mediator

THEMES = ("light", "dark")
DEFAULT_SHELL_THEME = "light"
DEFAULT_SHELL_MODE_ID = "normal_farm"
SHELL_BUNDLE_KEYS = frozenset({"_shell", "_shell_schema"})
PREFLIGHT_CHECK_IDS = ("mode_enabled", "live_lock", "skills_non_empty", "cycle_valid", "follow_pair_code")
SETTINGS_REVISION_KEY = "_dashboard_settings_revision"


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
        raw = self._read_bundle()
        self._shell: dict[str, Any] = dict(raw.get("_shell") or {})
        self._settings = Settings._from_dict(
            {k: v for k, v in raw.items() if k not in SHELL_BUNDLE_KEYS}
        )
        revision = raw.get(SETTINGS_REVISION_KEY, 0)
        self._settings_revision = revision if type(revision) is int and revision >= 0 else 0
        self._snapshot_seq = 0

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
        # mediator 未挂载时退回 worker 记录值（与原生 update_status 同语义）。
        return {
            "state": state,
            "mode_id": getattr(runner, "mode_id", None),
            "phase": phase or str(getattr(worker, "phase", "") or ""),
            "game_count": game_count,
            "cycle_num": max(0, int(self._settings.cycle_num)),
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
        if layout not in {"dashboard", "chooser"} or self._on_layout is None:
            return json.dumps(self._rpc_response(False, error=f"不支持的布局: {layout!r}"), ensure_ascii=False)
        self._on_layout(layout)
        return json.dumps(self._rpc_response(True), ensure_ascii=False)

    # ------------------------------------------------------------- 运行控制（§6.3）

    @Slot(str, result=str)
    def start_run(self, mode_id_json: str) -> str:
        """先内部 preflight，失败 {ok:false} 不建 worker；成功经 RunnerService 启动。"""
        pre = json.loads(self.validate_preflight(mode_id_json))
        if not pre["ok"]:
            return json.dumps(self._rpc_response(False, error=pre["blocked_reason"]),
                              ensure_ascii=False)
        payload = json.loads(mode_id_json) if isinstance(mode_id_json, str) and mode_id_json.strip().startswith("{") else {"mode_id": mode_id_json}
        expected_rev = payload.get("expected_settings_revision")
        if expected_rev is not None and int(expected_rev) != self._settings_revision:
            return json.dumps(self._rpc_response(False, error=f"Settings revision mismatch: expected {expected_rev}, current {self._settings_revision}"), ensure_ascii=False)
        mode_id = payload.get("mode_id") or self._parse_keyed(mode_id_json, "mode_id")
        runner = self._ensure_runner()
        if runner is None:
            return json.dumps(self._rpc_response(
                False, error="未注入 RunnerService 且缺少 root，无法启动",
            ), ensure_ascii=False)
        try:
            worker = runner.start(mode_id, self._settings)
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

    def _on_status_updated(self, running: bool, phase: str, game_count: int,
                           terminal_reason: str, ocr_status: str,
                           last_action: str) -> None:
        state = RUNNER_RUNNING if running else RUNNER_IDLE
        dto = {
            "state": str(getattr(self._runner, "runner_state", "") or state),
            "mode_id": getattr(self._runner, "mode_id", None),
            "phase": str(phase or ""),
            "game_count": max(0, int(game_count or 0)),
            "cycle_num": max(0, int(self._settings.cycle_num)),
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
