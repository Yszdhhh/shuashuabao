"""玩家画像采集：只读解析 + 落盘 %LocalAppData%/ShuaBao/profiles/。

不点击、不按键、不写 Settings、不写仓库 config。OCR 由调用方传入文本。
conf 低或读数超 KB 硬顶 → unverified / 丢弃，不编数。

TAB 只认进图默认盘（存档装备堆叠后的进图数值）。打一半升级/拿卡后的
面板是污染盘，海报七格保持未采集。认不清窗口 → unknown，同样不吃。
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shuabao.skill_catalog import _arcane_alias, load_skill_archive_unlocks, load_skill_catalog

PROFILE_VERSION = 1
MIN_CONF = 0.60
MAX_ARCHIVE_LEVEL = 50
LIVE_LOCK_NAME = "ShuaBao.live.lock"
_IS_WINDOWS = os.name == "nt"
# 存档技能格上的实机别名（2026-08-15 用户帧）。不另开卡名表。
_EXTRA_SKILL_ALIASES = {
    "byj": ("炽炎箭",),
    "dz": ("地刺",),
    "hq": ("烈焰",),
}
_KIND_STEM = {
    "skills": "skill_levels",
    "attrs": "tab_attrs",
    "equipment": "equipment",
    "bind": "first_login",
    "poster": "poster",
}
_POWER_RE = re.compile(r"(?:装备)?战力\s*[:：]?\s*(\d{3,6})")
_ENHANCE_RE = re.compile(r"强化(?:等级)?\s*[:：]?\s*(\d{1,4})")
_ROI_INT = re.compile(r"(\d{1,6})")
_HASTE_SLASH = re.compile(
    r"[\s\[\]:：.]*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*%?"
)
_WAVE_RE = re.compile(r"(?:波次|关卡)?\s*(?:第\s*)?([1-5])\s*/\s*5\b|第\s*([1-5])\s*波")
_CLOCK_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_KILLS_RE = re.compile(r"杀敌(?:数)?\s*[:：]?\s*(\d{1,6})")
_MID_RUN_HINTS = ("选择技能", "三选一", "技能三选", "刷新技能")
TAB_WINDOW_ENTRY = "entry"
TAB_WINDOW_MID_RUN = "mid_run"
TAB_WINDOW_UNKNOWN = "unknown"
TAB_HIGHLIGHT_KEYS = (
    "strength",
    "agility",
    "intelligence",
    "attack_speed",
    "crit",
    "skill_haste",
    "drop_rate",
)
_ENTRY_MAX_CLOCK_S = 20
_ENTRY_MAX_KILLS = 5
_MID_MIN_KILLS = 20
_MID_MIN_CLOCK_S = 60

_LEVEL_AFTER = re.compile(
    r"[\s\[\]:：.]*[Ll][Vv][\s.]*(\d{1,2})|[\s:：.]*(\d{1,2})\s*级?"
)
_NUMBER = re.compile(r"[\s\[\]:：.]*([+-]?\d+(?:\.\d+)?)\s*%?")


def shuabao_root() -> Path:
    from shuabao.paths import get_canonical_app_data_dir
    return get_canonical_app_data_dir()


def default_profile_dir() -> Path:
    from shuabao.paths import player_profile_dir
    return player_profile_dir()


def default_live_lock_path() -> Path:
    from shuabao.paths import live_lock_path
    return live_lock_path()


def _config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "config"


def load_mechanics_kb(path: Path | None = None) -> dict[str, Any]:
    target = path or (_config_dir() / "game_mechanics_kb.json")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def skill_families() -> tuple[dict[str, Any], ...]:
    """16 系：id / name / aliases。只读 archive unlocks + catalog 别名，不另开表。"""
    catalog_names = load_skill_catalog().get("family_to_code") or {}
    code_to_catalog = {str(code): str(name) for name, code in catalog_names.items()}
    out: list[dict[str, Any]] = []
    for row in load_skill_archive_unlocks().get("skills") or []:
        if not isinstance(row, dict):
            continue
        skill_id = str(row.get("skill_id") or "").strip()
        name = str(row.get("name") or "").strip()
        if not skill_id or not name:
            continue
        aliases = {name, skill_id}
        for alias in row.get("aliases") or []:
            text = str(alias).strip()
            if text:
                aliases.add(text)
        alt = _arcane_alias(name)
        if alt:
            aliases.add(alt)
        catalog_name = code_to_catalog.get(skill_id)
        if catalog_name:
            aliases.add(catalog_name)
            cat_alt = _arcane_alias(catalog_name)
            if cat_alt:
                aliases.add(cat_alt)
        aliases.update(_EXTRA_SKILL_ALIASES.get(skill_id, ()))
        out.append({
            "id": skill_id,
            "name": name,
            "aliases": tuple(sorted(aliases, key=len, reverse=True)),
        })
    return tuple(out)


def attr_schema(kb: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
    """TAB 面板字段：KB attributes + special_attributes + 硬顶。"""
    data = dict(kb) if kb is not None else load_mechanics_kb()
    caps_raw = data.get("caps") or {}
    cap_by_id = {
        "attack_speed": _cap_value(caps_raw.get("attack_speed_pct")),
        "skill_haste": _cap_value(caps_raw.get("skill_haste_pct")),
        "multi_damage": _cap_value(caps_raw.get("multi_damage_pct"), key="max"),
        "bounce_damage": _cap_value(caps_raw.get("bounce_damage_pct"), key="max"),
    }
    extra_aliases = {
        "attack": ("攻击", "攻击力"),
        "attack_speed": ("攻速", "攻击速度"),
        "crit": ("暴击", "暴击率", "致命一击"),
        "skill_haste": ("技能急速", "急速"),
        "drop_rate": ("掉宝率",),
        "hp": ("生命", "生命值"),
        "strength": ("力量",),
        "agility": ("敏捷",),
        "intelligence": ("智力",),
    }
    skip = {"save_attr_colors"}
    fields: list[dict[str, Any]] = []
    for group in ("attributes", "special_attributes"):
        block = data.get(group) or {}
        if not isinstance(block, Mapping):
            continue
        for field_id, row in block.items():
            if field_id in skip or not isinstance(row, Mapping):
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            aliases = {name}
            aliases.update(extra_aliases.get(field_id, ()))
            cap = row.get("cap_pct")
            if cap is None:
                cap = cap_by_id.get(field_id)
            try:
                cap_f = float(cap) if cap is not None else None
            except (TypeError, ValueError):
                cap_f = None
            fields.append({
                "id": str(field_id),
                "name": name,
                "aliases": tuple(sorted(aliases, key=len, reverse=True)),
                "cap": cap_f,
                "source": row.get("source") or group,
            })
    return tuple(fields)


def _cap_value(raw: Any, key: str = "value") -> float | None:
    if isinstance(raw, Mapping):
        raw = raw.get(key)
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def parse_skill_levels(
    text: str,
    *,
    conf: float = 1.0,
    families: Sequence[Mapping[str, Any]] | None = None,
    min_conf: float = MIN_CONF,
) -> dict[str, dict[str, Any]]:
    """从 OCR 文本抓 16 系等级。读不到的标 missing，不编数。"""
    blob = str(text or "")
    rows = families if families is not None else skill_families()
    consumed: list[tuple[int, int]] = []
    out: dict[str, dict[str, Any]] = {}
    alias_jobs: list[tuple[int, str, Mapping[str, Any]]] = []
    for fam in rows:
        for alias in fam.get("aliases") or ():
            alias_jobs.append((len(str(alias)), str(alias), fam))
    alias_jobs.sort(key=lambda item: (-item[0], item[1]))
    for _n, alias, fam in alias_jobs:
        skill_id = str(fam["id"])
        if skill_id in out and out[skill_id].get("level") is not None:
            continue
        hit = _find_number_after_label(blob, alias, consumed)
        if hit is None:
            continue
        level, span = hit
        if level < 0 or level > MAX_ARCHIVE_LEVEL:
            out[skill_id] = _skill_row(fam, None, conf, "rejected_bad_range")
            consumed.append(span)
            continue
        status = "verified" if conf >= min_conf else "unverified"
        out[skill_id] = _skill_row(fam, level, conf, status)
        consumed.append(span)
    for fam in rows:
        skill_id = str(fam["id"])
        if skill_id not in out:
            out[skill_id] = _skill_row(fam, None, 0.0, "missing")
    return out


def _hud_wave(text: str) -> int | None:
    hit = _WAVE_RE.search(text)
    if hit is None:
        return None
    raw = hit.group(1) or hit.group(2)
    return int(raw)


def _hud_clock_s(text: str) -> int | None:
    best: int | None = None
    for hit in _CLOCK_RE.finditer(text):
        minutes = int(hit.group(1))
        seconds = int(hit.group(2))
        if seconds > 59 or minutes > 59:
            continue
        total = minutes * 60 + seconds
        if best is None or total < best:
            best = total
    return best


def _hud_kills(text: str) -> int | None:
    hit = _KILLS_RE.search(text)
    return int(hit.group(1)) if hit is not None else None


def classify_tab_window(text: str) -> str:
    """进图默认盘 / 打一半污染盘 / 认不清。认不清不当画像。"""
    blob = str(text or "")
    wave = _hud_wave(blob)
    clock_s = _hud_clock_s(blob)
    kills = _hud_kills(blob)
    if any(hint in blob for hint in _MID_RUN_HINTS):
        return TAB_WINDOW_MID_RUN
    if wave is not None and wave >= 2:
        return TAB_WINDOW_MID_RUN
    if kills is not None and kills >= _MID_MIN_KILLS:
        return TAB_WINDOW_MID_RUN
    if clock_s is not None and clock_s >= _MID_MIN_CLOCK_S:
        return TAB_WINDOW_MID_RUN
    start_bits = 0
    if wave == 1:
        start_bits += 1
    if kills is not None and kills <= _ENTRY_MAX_KILLS:
        start_bits += 1
    if clock_s is not None and clock_s <= _ENTRY_MAX_CLOCK_S:
        start_bits += 1
    if start_bits >= 2:
        return TAB_WINDOW_ENTRY
    return TAB_WINDOW_UNKNOWN


def parse_attr_panel(
    text: str,
    *,
    conf: float = 1.0,
    schema: Sequence[Mapping[str, Any]] | None = None,
    min_conf: float = MIN_CONF,
) -> dict[str, dict[str, Any]]:
    """从 OCR 文本抓 TAB 属性。超硬顶 = OCR 错，丢弃。

    只解析数字。是否进海报由 classify_tab_window / build_poster 另判。
    """
    blob = str(text or "")
    fields = schema if schema is not None else attr_schema()
    consumed: list[tuple[int, int]] = []
    out: dict[str, dict[str, Any]] = {}
    jobs: list[tuple[int, str, Mapping[str, Any]]] = []
    for field in fields:
        for alias in field.get("aliases") or ():
            jobs.append((len(str(alias)), str(alias), field))
    jobs.sort(key=lambda item: (-item[0], item[1]))
    for _n, alias, field in jobs:
        field_id = str(field["id"])
        if field_id in out and out[field_id].get("value") is not None:
            continue
        hit = _find_attr_number(blob, alias, consumed, field_id=field_id)
        if hit is None:
            continue
        value, span = hit
        cap = field.get("cap")
        if cap is not None and value > float(cap):
            out[field_id] = _attr_row(field, None, conf, "rejected_over_cap")
            consumed.append(span)
            continue
        if value < 0:
            out[field_id] = _attr_row(field, None, conf, "rejected_bad_range")
            consumed.append(span)
            continue
        status = "verified" if conf >= min_conf else "unverified"
        out[field_id] = _attr_row(field, value, conf, status)
        consumed.append(span)
    for field in fields:
        field_id = str(field["id"])
        if field_id not in out:
            out[field_id] = _attr_row(field, None, 0.0, "missing")
    return out


def detect_scan_kind(text: str) -> str | None:
    """auto 用：能认到哪页就采哪页；都认不到 → None（fail-closed）。"""
    blob = str(text or "")
    if "属性面板" in blob or "增幅属性" in blob:
        return "attrs"
    if "一键分解" in blob or "整理背包" in blob:
        return "equipment"
    skill_hits = 0
    for fam in skill_families():
        if any(alias and alias in blob for alias in fam["aliases"] if len(str(alias)) >= 2):
            skill_hits += 1
    attr_hits = 0
    for field in attr_schema():
        if any(alias and alias in blob for alias in field["aliases"] if len(str(alias)) >= 2):
            attr_hits += 1
    if skill_hits >= 2 and skill_hits >= attr_hits:
        return "skills"
    if attr_hits >= 2:
        return "attrs"
    return None


def parse_equipment(
    text: str,
    *,
    conf: float = 1.0,
    power_text: str = "",
    enhance_text: str = "",
    min_conf: float = MIN_CONF,
) -> dict[str, dict[str, Any]]:
    """存档→装备：战力 + 强化等级。无标签且无 ROI 文本则 missing，不从背包数字里猜。"""
    blob = str(text or "")
    status = "verified" if conf >= min_conf else "unverified"
    power = _labeled_int(_POWER_RE, blob)
    if power is None:
        power = _roi_int(power_text, lo=100, hi=999999)
    enhance = _labeled_int(_ENHANCE_RE, blob)
    if enhance is None:
        enhance = _roi_int(enhance_text, lo=1, hi=9999)
    return {
        "combat_power": _equip_row("装备战力", power, conf, status if power is not None else "missing"),
        "enhance_level": _equip_row("强化等级", enhance, conf, status if enhance is not None else "missing"),
    }


def build_first_login(
    *,
    equipment: Mapping[str, Any] | None = None,
    skills: Mapping[str, Any] | None = None,
    opt_in: bool = False,
) -> dict[str, Any]:
    """第一次登录入库。未勾选画像绑定 → 不抓。"""
    if not opt_in:
        return {"kind": "first_login_bind", "opt_in": False, "skipped": True}
    return {
        "kind": "first_login_bind",
        "opt_in": True,
        "skipped": False,
        "equipment": dict(equipment or {}),
        "skills": dict(skills or {}),
    }


def build_poster(
    *,
    bind: Mapping[str, Any] | None = None,
    tab_attrs: Mapping[str, Any] | None = None,
    tab_window: str | None = None,
    hud_text: str = "",
) -> dict[str, Any]:
    """绑定底 + 进图 TAB 默认盘 → 海报。缺格 / 非开局帧写未采集，不编数。"""
    bind = dict(bind or {})
    equipment = bind.get("equipment") or {}
    skills = bind.get("skills") or {}
    attrs = dict(tab_attrs or {})
    window = str(tab_window or "").strip() or classify_tab_window(hud_text)
    if window not in (TAB_WINDOW_ENTRY, TAB_WINDOW_MID_RUN, TAB_WINDOW_UNKNOWN):
        window = TAB_WINDOW_UNKNOWN
    use_tab = window == TAB_WINDOW_ENTRY
    top = []
    for skill_id, row in skills.items():
        if not isinstance(row, Mapping):
            continue
        level = row.get("level")
        if isinstance(level, int) and row.get("status") == "verified":
            top.append((level, skill_id, str(row.get("name") or skill_id)))
    top.sort(reverse=True)
    return {
        "kind": "profile_poster",
        "combat_power": (equipment.get("combat_power") or {}).get("value"),
        "enhance_level": (equipment.get("enhance_level") or {}).get("value"),
        "top_skills": [
            {"id": skill_id, "name": name, "level": level} for level, skill_id, name in top[:5]
        ],
        "tab_window": window,
        "tab_highlights": {
            key: ((attrs.get(key) or {}).get("value") if use_tab else None)
            for key in TAB_HIGHLIGHT_KEYS
        },
        "bind_opt_in": bool(bind.get("opt_in")),
    }


def verified_skill_levels(parsed: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    """仅 verified 整数等级。P0 不写入 Settings；给 P2 / 手填对照用。"""
    out: dict[str, int] = {}
    for skill_id, row in parsed.items():
        if str(row.get("status") or "") != "verified":
            continue
        level = row.get("level")
        if isinstance(level, int) and 0 <= level <= MAX_ARCHIVE_LEVEL:
            out[str(skill_id)] = level
    return out


def write_profile(
    kind: str,
    payload: Mapping[str, Any],
    *,
    dest_dir: Path | None = None,
    day: str | None = None,
    frame_path: str = "",
) -> Path:
    """落盘 profile/，禁止写仓库 config。"""
    if kind not in _KIND_STEM:
        raise ValueError(f"unknown profile kind: {kind}")
    dest = Path(dest_dir) if dest_dir is not None else default_profile_dir()
    dest = dest.resolve()
    _assert_not_repo_config(dest)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = day or datetime.now().strftime("%Y%m%d")
    path = dest / f"{_KIND_STEM[kind]}_{stamp}.json"
    body = {
        "version": PROFILE_VERSION,
        "kind": _KIND_STEM[kind],
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_image": frame_path,
        "wrote_settings": False,
        **dict(payload),
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def upsert_first_login(
    *,
    dest_dir: Path,
    equipment: Mapping[str, Any] | None = None,
    skills: Mapping[str, Any] | None = None,
    day: str | None = None,
    opt_in: bool = False,
    frame_path: str = "",
) -> Path:
    """绑定入库：未 opt_in 只写 skipped。已有 first_login 则合并缺页。"""
    dest = Path(dest_dir)
    stamp = day or datetime.now().strftime("%Y%m%d")
    path = dest / f"first_login_{stamp}.json"
    prev: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prev = loaded
        except (OSError, ValueError, TypeError):
            prev = {}
    payload = build_first_login(
        equipment=equipment if equipment is not None else prev.get("equipment"),
        skills=skills if skills is not None else prev.get("skills"),
        opt_in=opt_in,
    )
    return write_profile("bind", payload, dest_dir=dest, day=stamp, frame_path=frame_path)


class LiveLaneBusy(RuntimeError):
    """真机车道已被占用（其它测试夹 bat / 看板 LIVE / 本采集器）。"""


class LiveLane:
    """%LocalAppData%/ShuaBao/ShuaBao.live.lock。同时间只占一条真机车道。"""

    def __init__(self, owner: str, path: Path | None = None):
        self.owner = owner
        self.path = Path(path) if path is not None else default_live_lock_path()
        self._held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_file():
            existing = _read_lock(self.path)
            pid = int(existing.get("pid") or 0)
            if pid and _pid_alive(pid):
                raise LiveLaneBusy(
                    f"真机车道占用中：{existing.get('owner') or '?'} pid={pid}。"
                    "先停 08/09/10/看板 LIVE 再采。"
                )
            try:
                self.path.unlink()
            except OSError as exc:
                raise LiveLaneBusy(f"无法清掉过期车道锁: {self.path}") from exc
        payload = {
            "pid": os.getpid(),
            "owner": self.owner,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(self.path), flags)
        except FileExistsError as exc:
            raise LiveLaneBusy(f"真机车道刚被占用: {self.path}") from exc
        try:
            os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        finally:
            os.close(fd)
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        existing = _read_lock(self.path) if self.path.is_file() else {}
        if int(existing.get("pid") or 0) in {0, os.getpid()}:
            try:
                self.path.unlink()
            except OSError:
                pass
        self._held = False

    def __enter__(self) -> "LiveLane":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def _skill_row(fam: Mapping[str, Any], level: int | None, conf: float, status: str) -> dict[str, Any]:
    return {
        "name": str(fam.get("name") or ""),
        "level": level,
        "conf": round(float(conf), 4),
        "status": status,
        "crop": "",
    }


def _equip_row(name: str, value: int | None, conf: float, status: str) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "conf": round(float(conf), 4),
        "status": status,
    }


def _labeled_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    if not match:
        return None
    return int(match.group(1))


def _roi_int(text: str, *, lo: int, hi: int) -> int | None:
    match = _ROI_INT.search(str(text or ""))
    if not match:
        return None
    value = int(match.group(1))
    if value < lo or value > hi:
        return None
    return value


def _attr_row(field: Mapping[str, Any], value: float | None, conf: float, status: str) -> dict[str, Any]:
    return {
        "name": str(field.get("name") or ""),
        "value": value,
        "conf": round(float(conf), 4),
        "status": status,
        "cap": field.get("cap"),
        "source": field.get("source") or "game_mechanics_kb",
    }


def _overlaps(span: tuple[int, int], used: Sequence[tuple[int, int]]) -> bool:
    a0, a1 = span
    for b0, b1 in used:
        if a0 < b1 and b0 < a1:
            return True
    return False


def _find_number_after_label(
    text: str, alias: str, used: Sequence[tuple[int, int]]
) -> tuple[int, tuple[int, int]] | None:
    if not alias:
        return None
    start = 0
    while True:
        idx = text.find(alias, start)
        if idx < 0:
            return None
        label_end = idx + len(alias)
        if _overlaps((idx, label_end), used):
            start = label_end
            continue
        window = text[label_end:label_end + 12]
        match = _LEVEL_AFTER.match(window)
        if match:
            raw = match.group(1) or match.group(2)
            span = (idx, label_end + match.end())
            if not _overlaps(span, used):
                return int(raw), span
        start = label_end


def _find_attr_number(
    text: str,
    alias: str,
    used: Sequence[tuple[int, int]],
    *,
    field_id: str = "",
) -> tuple[float, tuple[int, int]] | None:
    if not alias:
        return None
    start = 0
    while True:
        idx = text.find(alias, start)
        if idx < 0:
            return None
        label_end = idx + len(alias)
        if _overlaps((idx, label_end), used):
            start = label_end
            continue
        window = text[label_end:label_end + 20]
        if field_id == "skill_haste":
            slash = _HASTE_SLASH.match(window)
            if slash:
                span = (idx, label_end + slash.end())
                if not _overlaps(span, used):
                    return float(slash.group(2)), span
        match = _NUMBER.match(window)
        if match:
            span = (idx, label_end + match.end())
            if not _overlaps(span, used):
                return float(match.group(1)), span
        start = label_end


def _read_lock(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _windows_pid_alive(pid: int, kernel32: Any | None = None) -> bool:
    """Query one Windows process without sending a console control event.

    ``os.kill(pid, 0)`` is the conventional POSIX existence probe, but Python's
    Windows implementation may route signal 0 through console-control handling.
    A profile-lock liveness check must therefore use a process handle instead of
    signalling the target process.
    """
    try:
        import ctypes
        from ctypes import wintypes

        api = kernel32 or ctypes.WinDLL("kernel32", use_last_error=True)
        if kernel32 is None:
            # Explicit pointer-width signatures are required on 64-bit Windows;
            # ctypes' default c_int return type can truncate a HANDLE.
            api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            api.OpenProcess.restype = wintypes.HANDLE
            api.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
            ]
            api.GetExitCodeProcess.restype = wintypes.BOOL
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.CloseHandle.restype = wintypes.BOOL
        handle = api.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not api.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return int(exit_code.value) == 259  # STILL_ACTIVE
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    finally:
        try:
            api.CloseHandle(handle)
        except (AttributeError, OSError, TypeError, ValueError):
            pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _IS_WINDOWS:
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists but the current user cannot signal it.
        return True
    except OSError:
        return False
    return True


def _assert_not_repo_config(dest: Path) -> None:
    repo_config = _config_dir().resolve()
    resolved = dest.resolve()
    if resolved == repo_config or repo_config in resolved.parents:
        raise ValueError(f"画像禁止写入仓库 config: {dest}")
