#!/usr/bin/env python3
"""整夜实验室：只跑一种三选一面板 + 退出再进，并把 OCR 槽位落到本机 panels。

不改 default_settings.json。学习模式（--dry-run）只观察、不会刷出新面板。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.bond_capacity import stack_need
from shuabao.incidents import default_incident_dir
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal

try:
    from shuabao.mediator import LAB_BOND_MAX_REFRESHES, LAB_REENTER_SAMPLE_S
except ImportError:
    LAB_BOND_MAX_REFRESHES = 20
    LAB_REENTER_SAMPLE_S = 720.0

try:
    from shuabao.settings import _normalize_lab_focus
except ImportError:  # Local Settings 还没有实验室字段时，lab_run 自己认 token
    _LAB_FOCUS_TOKENS = frozenset({"skill", "bond", "treasure", "reenter"})

    def _normalize_lab_focus(raw: Any) -> str:
        if isinstance(raw, (list, tuple)):
            parts = [str(x).strip().lower() for x in raw if str(x).strip()]
        else:
            text = str(raw or "").replace(";", ",")
            parts = [p.strip().lower() for p in text.split(",") if p.strip()]
        return ",".join(p for p in parts if p in _LAB_FOCUS_TOKENS)

PRESETS = {
    "reenter": "reenter",
    "bond": "bond,reenter",
    "skill": "skill,reenter",
    "skillbond": "skill,bond,reenter",
    "treasure": "treasure,reenter",
    "catalogs": "skill,bond,treasure,reenter",
    "merchant": "skill,bond,treasure,reenter",
}

def _card_ref(name: str, code_of: dict[str, str]) -> str:
    """规范名 → fetter 短码（有短码才有 cards/*.png 字模兜底），没有就用中文。"""
    return code_of.get(name, name)


def _route_cards(
    priority: dict, route: dict, code_of: dict[str, str]
) -> list[str]:
    """按 bond_priority 的分层拼白名单：靠前的先拿。

    第一轮必做 → **整条属性链（含末环 UR）** → 生存/破甲 → 必选衍生卡 →
    第四轮选做（实验室会按 lab_skip 丢掉）→ 该系辅助卡。
    ``not_recommended``（剑术）不入白名单。
    属性链整条压过生存卡：UR 是链的产出，体术这类通用卡全程都能补。
    「差 1 张吞噬」在 choice_policy 里仍然压过本顺序，用来腾格子。
    """
    skip = {str(n) for n in (priority.get("lab_skip") or [])}
    names = [
        *priority["round1_must"],
        *route["chain"],
        *priority["round3_survival"],
        *priority["must_take"],
        *priority["round4_optional"],
        *route["support"],
    ]
    seen: set[str] = set()
    ordered = [n for n in names if n not in skip and not (n in seen or seen.add(n))]
    return [_card_ref(n, code_of) for n in ordered]


def _attr_routes() -> dict[str, list[str]]:
    """白名单由 bond_priority + attr_routes.chain 生成，改配置不用再改代码。"""
    pack = json.loads(
        (ROOT / "config" / "official_strategy_defaults.json").read_text(encoding="utf-8")
    )
    labels = json.loads(
        (ROOT / "config" / "fetter_labels.json").read_text(encoding="utf-8")
    )
    code_of = {v: k for k, v in labels.items() if not str(k).startswith("_")}
    priority, routes = pack["bond_priority"], pack["attr_routes"]
    return {
        key: _route_cards(priority, routes[key], code_of)
        for key in ("intelligence", "strength", "agility")
    }


ATTR_ROUTE_CARDS = _attr_routes()

# 多线长测：每条属性线换匹配流派。单线（03c）不走这里，沿用 default_settings。
ROUTE_DEFAULT_BUILDS = {
    "intelligence": "arcane_open",
    "strength": "sword_qi",
    "agility": "aa_universal",
}


def _chain_of(route: str) -> list[str]:
    """该条线的必经链路（首环=门卡，末环=UR）；未知路线返回空。"""
    pack = json.loads(
        (ROOT / "config" / "official_strategy_defaults.json").read_text(encoding="utf-8")
    )
    entry = pack["attr_routes"].get(route)
    return list(entry["chain"]) if isinstance(entry, dict) else []


def _skill_family_codes() -> dict[str, str]:
    raw = json.loads(
        (ROOT / "config" / "skill_card_catalog.json").read_text(encoding="utf-8")
    )
    mapping = raw.get("family_to_code") or {}
    return {str(k): str(v) for k, v in mapping.items() if str(k).strip() and str(v).strip()}


def _skill_synergy() -> dict[str, Any]:
    pack = json.loads(
        (ROOT / "config" / "official_strategy_defaults.json").read_text(encoding="utf-8")
    )
    syn = pack.get("skill_synergy")
    return syn if isinstance(syn, dict) else {}


def _resolve_skill_family(explicit: str, kinds: frozenset[str]) -> str:
    """仅在调用方显式传入 --skill-family 时收窄。默认沿用 default_settings 四系。"""
    del kinds
    codes = _skill_family_codes()
    name = (explicit or "").strip()
    if not name:
        return ""
    if name not in codes:
        raise ValueError(f"unknown skill family {name!r}；可选 {sorted(codes)}")
    return name


def _builds() -> dict[str, dict[str, Any]]:
    """official_strategy_defaults 里的成套流派：id → build。"""
    pack = json.loads(
        (ROOT / "config" / "official_strategy_defaults.json").read_text(encoding="utf-8")
    )
    return {str(b["id"]): b for b in (pack.get("builds") or []) if b.get("id")}


def _resolve_build(explicit: str) -> dict[str, Any] | None:
    """--build 套用整套流派的 4 个技能短码（`--skill-family` 只能收成单系）。"""
    name = (explicit or "").strip()
    if not name:
        return None
    builds = _builds()
    if name not in builds:
        raise ValueError(f"unknown build {name!r}；可选 {sorted(builds)}")
    return builds[name]


def _desired_bond_cards(family: str) -> list[str]:
    names = (_skill_synergy().get("desired_bonds_by_family") or {}).get(family) or []
    labels = json.loads(
        (ROOT / "config" / "fetter_labels.json").read_text(encoding="utf-8")
    )
    code_of = {v: k for k, v in labels.items() if not str(k).startswith("_")}
    return [_card_ref(str(n).strip(), code_of) for n in names if str(n).strip()]


def shuabao_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "ShuaBao"


DASHBOARD_SETTINGS_NAME = "user_settings.json"
DEFAULT_CATALOG_EXIT_BONDS = (
    "解放的圣剑,圣人,祖龙,世界末日迦拉克隆,世界末日,吞食天地,"
    "帝炎,陀舍古帝,帝炎陀舍古帝,萨格拉斯,兵主,大乘期,法天象地"
)
_LAB_PANEL_KINDS = frozenset({"skill", "bond", "treasure"})


class LabConfigError(Exception):
    """没有看板保存、也没有可用的 --config。禁止回落出厂默认。"""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def dashboard_settings_path() -> Path:
    return shuabao_data_dir() / DASHBOARD_SETTINGS_NAME


def missing_dashboard_message(path: Path | None = None) -> str:
    target = path or dashboard_settings_path()
    return (
        "先打开刷刷宝控制室，勾好技能/关卡/英雄模式，等自动保存（或点保存），再跑测试。\n"
        f"缺少看板文件：{target}\n"
        "禁止偷偷使用仓库 default_settings.json。"
    )


def resolve_lab_config(explicit: str | Path | None) -> tuple[Path, str]:
    """有 --config 且文件存在 → 用它；否则看板；否则报错。不回落出厂默认。"""
    text = str(explicit or "").strip()
    if text:
        path = Path(text)
        if path.is_file():
            return path, "显式文件"
        raise LabConfigError(f"指定的 --config 不存在：{path}")
    dash = dashboard_settings_path()
    if dash.is_file():
        return dash, "看板"
    raise LabConfigError(missing_dashboard_message(dash))


def load_lab_settings(path: Path) -> Settings:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise LabConfigError(f"设置文件不是 JSON 对象：{path}")
    raw.pop("_shell", None)
    return Settings._from_dict(raw)


def format_lab_config_report(settings: Settings, config: Path, source: str) -> str:
    hero = "开" if settings.auto_reputation else "关"
    stages = settings.stage_targets or [f"{settings.stage1}-{settings.stage2}"]
    return (
        f"[lab] config={source} {config} "
        f"关卡={list(stages)} 英雄模式={hero} "
        f"skills={list(settings.skills)} cards={list(settings.cards)}"
    )


def _lab_focus_kinds(settings: Settings) -> frozenset[str]:
    fn = getattr(settings, "lab_focus_kinds", None)
    if callable(fn):
        return fn()
    tokens = {
        p.strip().lower()
        for p in str(getattr(settings, "lab_focus", "") or "").replace(";", ",").split(",")
        if p.strip()
    }
    return frozenset(t for t in tokens if t in _LAB_PANEL_KINDS)


def _lab_reenter(settings: Settings) -> bool:
    fn = getattr(settings, "lab_reenter", None)
    if callable(fn):
        return fn()
    tokens = {
        p.strip().lower()
        for p in str(getattr(settings, "lab_focus", "") or "").replace(";", ",").split(",")
        if p.strip()
    }
    return "reenter" in tokens


def _lab_immediate_quit(settings: Settings) -> bool:
    fn = getattr(settings, "lab_immediate_quit", None)
    if callable(fn):
        return fn()
    return _lab_reenter(settings) and not _lab_focus_kinds(settings)


def apply_lab_preset(
    settings: Settings,
    focus: str,
    *,
    games: int | None = None,
    route: str = "",
    stage: str = "",
    skill_family: str = "",
    build: str = "",
    vary_builds: bool = False,
) -> Settings:
    settings.lab_focus = _normalize_lab_focus(focus)
    settings.dry_run = False
    tokens = {
        p.strip().lower()
        for p in str(settings.lab_focus or "").replace(";", ",").split(",")
        if p.strip()
    }
    # 局数：只有 CLI 显式传了 --games 才覆盖看板 cycle_num。
    if games is not None:
        if "reenter" in tokens or games > 1:
            settings.cycle_num = max(1, min(999, int(games)))
        else:
            settings.cycle_num = 1
    # 英雄模式由看板 auto_reputation 说了算，禁止再强制「实验室一律非英雄」。
    if stage:
        settings.stage_targets = [stage]
    # 拿到本条线的 UR 就退出本局，不等采样预算（user 20260813）。
    if key := (route or "").strip().lower():
        chain = _chain_of(key)
        if chain:
            settings.lab_exit_on_bond = chain[-1]
            settings.lab_exit_on_bond_count = stack_need(chain[-1]) or 1
    settings.failure_streak_limit = 10
    # 40 次点击约 3 分钟就退，而走完一条属性链要 14 张卡加开荒/生存两轮；
    # 20260813 实测力量/敏捷刚好卡在 UR 差一张，智力更是只到秘法师 2/4。
    # 真正的收口仍是 LAB_REENTER_SAMPLE_S（12 分钟），本预算只是兜底。
    settings.panel_episode_limit_per_kind = 80
    kinds = _lab_focus_kinds(settings)
    if _lab_immediate_quit(settings):
        settings.ocr_mode = "off"
        settings.auto_bond = False
        settings.auto_treasure = False
        settings.auto_card = False
        settings.auto_secret_realm = False
    else:
        settings.ocr_mode = "live"
        if kinds:
            settings.auto_bond = "bond" in kinds
            settings.auto_treasure = "treasure" in kinds
            settings.auto_card = "skill" in kinds
            settings.auto_weapon = False
            settings.auto_artifact = False
    key = (route or "").strip().lower()
    # 成套流派：直接套 build 的 4 个技能短码。与 --skill-family 互斥（单系收窄）。
    spec = _resolve_build(build)
    if spec is None and vary_builds and not str(skill_family or "").strip():
        default_id = ROUTE_DEFAULT_BUILDS.get(key)
        if default_id and "skill" in kinds:
            spec = _resolve_build(default_id)
    if spec is not None:
        if str(skill_family or "").strip():
            raise ValueError("--build 与 --skill-family 互斥：前者套整套流派，后者收成单系")
        codes = [str(c) for c in (spec.get("skills") or []) if str(c).strip()]
        if not codes:
            raise ValueError(f"build {spec.get('id')!r} 没有 skills")
        settings.skills = codes
    family = _resolve_skill_family(skill_family, kinds)
    if family:
        settings.skills = [_skill_family_codes()[family]]
        if "bond" in kinds and not key:
            bonds = _desired_bond_cards(family)
            if bonds:
                settings.cards = bonds
    if key:
        if key not in ATTR_ROUTE_CARDS:
            raise ValueError(f"unknown attr route {route!r}")
        settings.cards = list(ATTR_ROUTE_CARDS[key])
    # catalogs 且没配退局目标：用默认 EX 名。Local Settings 无该字段则跳过。
    if kinds >= {"skill", "bond", "treasure"} and hasattr(settings, "lab_exit_on_bond"):
        if not str(getattr(settings, "lab_exit_on_bond", "") or "").strip():
            settings.lab_exit_on_bond = DEFAULT_CATALOG_EXIT_BONDS
            settings.lab_exit_on_bond_count = 1
    return settings


def catalog_names(root: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {"skill": set(), "bond": set(), "treasure": set()}
    skill_path = root / "config" / "skill_card_catalog.json"
    if skill_path.is_file():
        raw = json.loads(skill_path.read_text(encoding="utf-8"))
        for card in raw.get("cards") or []:
            if isinstance(card, dict) and card.get("name"):
                out["skill"].add(str(card["name"]).strip())
    fetter_path = root / "config" / "fetter_labels.json"
    if fetter_path.is_file():
        raw = json.loads(fetter_path.read_text(encoding="utf-8"))
        for key, value in raw.items():
            if str(key).startswith("_") or not isinstance(value, str):
                continue
            out["bond"].add(value.strip())
    lex_path = root / "config" / "choice_lexicon.json"
    if lex_path.is_file():
        entries = json.loads(lex_path.read_text(encoding="utf-8")).get("entries") or {}
        for name, meta in entries.items():
            if not isinstance(meta, dict):
                continue
            kind = str(meta.get("kind") or "")
            if kind in out:
                out[kind].add(str(name).strip())
    return out


def _iter_panel_json(data_dir: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in ("incidents/*/panels/*.json", "*/panels/*.json"):
        found.extend(p for p in data_dir.glob(pattern) if p.is_file())
    return sorted(set(found))


def _slot_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for slot in payload.get("ocr_slots") or []:
        if not isinstance(slot, dict):
            continue
        text = str(slot.get("name") or "").strip() or str(slot.get("raw_text") or "").strip()
        if text:
            names.append(text)
    return names


def coverage_report(
    catalogs: dict[str, set[str]],
    panel_files: list[Path],
    observation_files: list[Path] | None = None,
) -> dict[str, Any]:
    seen: dict[str, set[str]] = defaultdict(set)
    unknown: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    unlabeled = 0
    for path in panel_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        kind = str(payload.get("panel_kind") or "")
        counts[kind] += 1
        names = _slot_names(payload)
        if not names:
            unlabeled += 1
            continue
        catalog = catalogs.get(kind, set())
        for name in names:
            if catalog and name in catalog:
                seen[kind].add(name)
            elif catalog:
                unknown[kind].add(name)
            else:
                seen[kind].add(name)
    for path in observation_files or []:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            kind = str(row.get("panel_kind") or "")
            for slot in row.get("slots") or []:
                if not isinstance(slot, dict):
                    continue
                name = str(slot.get("name") or "").strip()
                if not name:
                    continue
                catalog = catalogs.get(kind, set())
                if catalog and name in catalog:
                    seen[kind].add(name)
                elif catalog:
                    unknown[kind].add(name)
    kinds = sorted(set(catalogs) | set(counts) | set(seen))
    by_kind = {}
    for kind in kinds:
        catalog = catalogs.get(kind, set())
        hit = seen.get(kind, set())
        by_kind[kind] = {
            "panels": counts.get(kind, 0),
            "catalog": len(catalog),
            "seen": sorted(hit),
            "missing": sorted(catalog - hit) if catalog else [],
            "unknown": sorted(unknown.get(kind, set())),
            "coverage": round(len(hit) / len(catalog), 3) if catalog else None,
        }
    return {
        "panel_files": len(panel_files),
        "unlabeled_panels": unlabeled,
        "by_kind": by_kind,
    }


def cmd_eval(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir) if args.data_dir else shuabao_data_dir()
    catalogs = catalog_names(ROOT)
    panels = _iter_panel_json(data_dir)
    observations = sorted((data_dir / "learning").glob("observations_*.jsonl"))
    report = coverage_report(catalogs, panels, observations)
    out_dir = data_dir / "lab"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"coverage_{stamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[lab] 评测 {out_path}")
    print(f"[lab] 面板 json {report['panel_files']} 张，无 OCR 槽位 {report['unlabeled_panels']}")
    for kind, row in report["by_kind"].items():
        cov = row["coverage"]
        cov_s = f"{cov:.0%}" if isinstance(cov, float) else "-"
        print(
            f"[lab] {kind}: 面板 {row['panels']} 库 {row['catalog']} "
            f"见过 {len(row['seen'])} 覆盖 {cov_s} "
            f"未识别 {len(row['unknown'])} 未见 {len(row['missing'])}"
        )
        if row["unknown"]:
            print(f"       OCR 不在库里: {', '.join(row['unknown'][:12])}")
        if row["missing"] and len(row["missing"]) <= 20:
            print(f"       库里还没刷到: {', '.join(row['missing'][:20])}")
    if report["panel_files"] == 0:
        print("[lab] 还没有 panels。先跑 --preset bond 过夜，再 --eval。")
        return 1
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """按 --route 依次跑一条或多条属性线，每条一份独立 trace。

    多条线时 --games 是「每条线的局数」，--hours 是整个序列的总时限。
    """
    routes = [r.strip() for r in str(args.route or "").split(",") if r.strip()]
    deadline = time.monotonic() + args.hours * 3600 if args.hours > 0 else None
    vary_builds = (
        len(routes) > 1
        and not str(getattr(args, "build", "") or "").strip()
        and not str(getattr(args, "skill_family", "") or "").strip()
    )
    if len(routes) <= 1:
        return _run_one(args, routes[0] if routes else "", deadline, vary_builds=False)
    print(f"[lab] 三线循环：{' → '.join(routes)}，每条 {args.games} 局", flush=True)
    if vary_builds:
        mapped = " / ".join(
            f"{r}={ROUTE_DEFAULT_BUILDS.get(r, '?')}" for r in routes
        )
        print(f"[lab] 多线换流派：{mapped}", flush=True)
    for i, route in enumerate(routes, 1):
        if deadline is not None and time.monotonic() >= deadline:
            print(f"[lab] 总时限到，跳过剩余线路（停在第 {i - 1}/{len(routes)} 条）", flush=True)
            break
        print(f"\n{'=' * 60}\n[lab] 第 {i}/{len(routes)} 条线：{route}\n{'=' * 60}", flush=True)
        code = _run_one(args, route, deadline, vary_builds=vary_builds)
        if code != 0:
            return code
    return 0


def _run_one(
    args: argparse.Namespace,
    route: str,
    deadline: float | None,
    vary_builds: bool = False,
) -> int:
    focus = args.focus or PRESETS[args.preset]
    try:
        config, source = resolve_lab_config(getattr(args, "config", "") or "")
    except LabConfigError as exc:
        print(f"[lab] {exc}", file=sys.stderr)
        return int(exc.code)
    settings = load_lab_settings(config)
    apply_lab_preset(
        settings,
        focus,
        games=args.games,
        route=route,
        stage=getattr(args, "stage", "") or "",
        skill_family=getattr(args, "skill_family", "") or "",
        build=getattr(args, "build", "") or "",
        vary_builds=vary_builds,
    )
    if args.dry_run:
        settings.dry_run = True
        print("[lab] 学习模式：不会点出新面板，只适合对着已打开的界面观察。")
    kinds = _lab_focus_kinds(settings)
    print(format_lab_config_report(settings, config, source))
    print(
        f"[lab] preset={args.preset} lab_focus={getattr(settings, 'lab_focus', '') or '-'} "
        f"kinds={sorted(kinds) or 'all'} cycle_num={settings.cycle_num} "
        f"hours={args.hours} route={route or '-'}"
    )
    print("[lab] 自动任务+四挑战会开（攒羁绊点）。实验室不点装备/神器。进化/黑商仍处理。")
    if "skill" in kinds:
        print("[lab] 技能三选只拿当前系（卡名或套系命中）；蓄力射击 never_pick。")
    if "bond" in kinds:
        print(
            "[lab] 羁绊不在白名单时点「刷新」（不含费用数字），不会一上来隐藏。"
            f"本面板最多刷新 {LAB_BOND_MAX_REFRESHES} 次。"
        )
    if "treasure" in kinds:
        print(
            "[lab] 宝物：EX 四宝必拿，负面默认 ban。羁绊结束后转 V，"
            "宝物结束后走进化→捡取→黑商（只买木材/吞噬丹），再回技能。"
        )
    if _lab_reenter(settings) and not _lab_immediate_quit(settings):
        exit_bond = str(getattr(settings, "lab_exit_on_bond", "") or "")
        exit_count = int(getattr(settings, "lab_exit_on_bond_count", 1) or 1)
        if exit_bond:
            print(
                f"[lab] 拿到 {exit_bond} x{exit_count} "
                f"就退出回房再开，共 {settings.cycle_num} 局"
                f"（兜底上限：焦点面板 {settings.panel_episode_limit_per_kind} 次或约 "
                f"{int(LAB_REENTER_SAMPLE_S / 60)} 分钟）。"
            )
        else:
            print(
                f"[lab] 本局采完（焦点面板 {settings.panel_episode_limit_per_kind} 次"
                f"或约 {int(LAB_REENTER_SAMPLE_S / 60)} 分钟）后退出回房再开，共 {settings.cycle_num} 局。"
            )
    print("[lab] 面板帧写入 %LocalAppData%\\ShuaBao\\incidents\\日期\\panels\\")
    print("[lab] tick trace 写入 %LocalAppData%\\ShuaBao\\当天\\trace_lab_*.jsonl")
    print("[lab] 不要同时开刷刷宝看板。结束本窗口或 Ctrl+C 停止。")
    if _lab_focus_kinds(settings):
        print("[lab] 可从已进局或暂停画面开：暂停会点继续游戏，不会一上来就退。")
    incident_dir = default_incident_dir()
    stop = StopSignal()
    from shuabao.mediator import Mediator
    med = Mediator(settings, ROOT, stop_signal=stop, incident_dir=incident_dir)
    now = datetime.now()
    tag = f"_{route}" if route else ""
    trace_path = (
        shuabao_data_dir() / now.strftime("%Y%m%d")
        / f"trace_lab_{now.strftime('%Y%m%d_%H%M%S')}{tag}.jsonl"
    )
    try:
        med.set_trace(str(trace_path))
        print(f"[lab] trace {trace_path}", flush=True)
    except OSError as exc:
        print(f"[lab] 无法开启 trace: {exc}", flush=True)
    if deadline is not None:
        remaining = max(0.0, deadline - time.monotonic())

        def _stop_later() -> None:
            time.sleep(remaining)
            print(f"[lab] 总时限 {args.hours} 小时到，停止", flush=True)
            med.stop()

        threading.Thread(target=_stop_later, daemon=True).start()
    try:
        med.run()
    except KeyboardInterrupt:
        print("[lab] interrupted")
        med.stop()
    finally:
        med.set_trace(None)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="整夜实验室：单素材采集 / 库覆盖评测")
    p.add_argument("--preset", choices=sorted(PRESETS), default="bond")
    p.add_argument("--focus", default="", help="覆盖预设，如 bond,reenter")
    p.add_argument("--hours", type=float, default=8.0, help="0=不限时，直到 cycle_num 或连败停")
    p.add_argument(
        "--games",
        type=int,
        default=None,
        help="这次实验局数；不传则用看板 cycle_num",
    )
    p.add_argument("--config", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--route",
        default=None,
        help=(
            "羁绊属性线，覆盖 settings.cards。可逗号分隔依次跑，"
            "如 intelligence,strength,agility；此时 --games 是每条线的局数，"
            f"--hours 是整个序列的总时限。可选：{'/'.join(sorted(ATTR_ROUTE_CARDS))}"
        ),
    )
    p.add_argument(
        "--stage",
        default="",
        help="仅当显式传入才覆盖看板关卡，格式 章-关 如 1-8",
    )
    p.add_argument(
        "--skill-family",
        default="",
        help=(
            "技能系中文名，如 奥数箭/天雷。留空则沿用 default_settings 的 "
            "asj/asjg/assx/jq，不自动收成单系"
        ),
    )
    p.add_argument(
        "--build",
        default="",
        help=(
            "成套流派 id（official_strategy_defaults.builds），套用整套 4 个技能短码。"
            f"可选：{'/'.join(sorted(_builds()))}。与 --skill-family 互斥"
        ),
    )
    p.add_argument("--eval", action="store_true", help="只评测已落盘 panels，不启动点击")
    # argparse 会对 help 做 % 插值，%LocalAppData% 必须写成 %%（否则 --help 直接崩）。
    p.add_argument("--data-dir", default="", help="评测根目录，默认 %%LocalAppData%%\\ShuaBao")
    args = p.parse_args()
    if args.eval:
        return cmd_eval(args)
    unknown = [
        r.strip()
        for r in str(args.route or "").split(",")
        if r.strip() and r.strip() not in ATTR_ROUTE_CARDS
    ]
    if unknown:
        p.error(f"unknown attr route {unknown}；可选 {sorted(ATTR_ROUTE_CARDS)}")
    family = str(args.skill_family or "").strip()
    if family:
        codes = _skill_family_codes()
        if family not in codes:
            p.error(f"unknown skill family {family!r}；可选 {sorted(codes)}")
    build = str(args.build or "").strip()
    if build:
        if family:
            p.error("--build 与 --skill-family 互斥：前者套整套流派，后者收成单系")
        if build not in _builds():
            p.error(f"unknown build {build!r}；可选 {sorted(_builds())}")
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
