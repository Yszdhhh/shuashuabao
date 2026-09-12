"""Offline hitch review inventories and classifier matrix; never captures or inputs.

Run with --static and/or --frames. Each decodable image in both fixture roots is
listed, including crops and images of unknown provenance (not claimed as live).
Full-size images are classified in fresh, pending-archive and boss-active contexts.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import hashlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs/reviews/hitch_review_20260912"


def write_csv(name, rows, fields):
    with (OUT / name).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def static_inventory():
    refs = {}
    returns = []
    resets = []
    methods = {}
    for filename in ("mediator.py", "runtime_mediator.py"):
        path = ROOT / "src/shuabao" / filename
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            for fn in [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                if cls.name == "Mediator":
                    methods.setdefault(filename, {})[fn.name] = fn.lineno
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"clear", "append", "extend", "add", "discard", "remove", "pop", "update", "setdefault"}:
                        target = node.func.value
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                            refs.setdefault(target.attr, {"read": set(), "write": set(), "init": set()})["write"].add(f"{filename}:{fn.name}:{node.lineno} (mutation)")
                    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
                        target = node.value
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                            refs.setdefault(target.attr, {"read": set(), "write": set(), "init": set()})["write"].add(f"{filename}:{fn.name}:{node.lineno} (item)")
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
                        field = node.attr
                        if not field.startswith("_"):
                            continue
                        item = refs.setdefault(field, {"read": set(), "write": set(), "init": set()})
                        kind = "write" if isinstance(node.ctx, ast.Store) else "read"
                        item[kind].add(f"{filename}:{fn.name}:{node.lineno}")
                    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        for target in targets:
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                                if fn.name == "__init__":
                                    refs.setdefault(target.attr, {"read": set(), "write": set(), "init": set()})["init"].add(ast.unparse(node.value) if node.value else "")
                                if fn.name in {"set_phase", "_hitch_after_exit", "_finish_hitch_round"}:
                                    resets.append(dict(file=filename, function=fn.name, line=node.lineno, field=target.attr, value=ast.unparse(node.value)))
                    # getattr/setattr are real references too.
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"getattr", "setattr", "hasattr"} and len(node.args) >= 2:
                        obj, name = node.args[:2]
                        if isinstance(obj, ast.Name) and obj.id == "self" and isinstance(name, ast.Constant) and isinstance(name.value, str):
                            item = refs.setdefault(name.value, {"read": set(), "write": set(), "init": set()})
                            item["write" if node.func.id == "setattr" else "read"].add(f"{filename}:{fn.name}:{node.lineno}")
                if fn.name == "_tick_main_line":
                    def visit(node, conditions=()):
                        if isinstance(node, ast.If):
                            cond = ast.unparse(node.test)
                            for child in node.body:
                                visit(child, conditions + (cond,))
                            for child in node.orelse:
                                visit(child, conditions + (f"NOT ({cond})",))
                            return
                        if isinstance(node, ast.Return) and node.value and ast.unparse(node.value) == "LoopAction.Continue":
                            lines = source.splitlines()
                            returns.append(dict(file=filename, line=node.lineno, conditions=" AND ".join(conditions), preceding=" | ".join(lines[max(fn.lineno-1,node.lineno-5):node.lineno-1])))
                        for child in ast.iter_child_nodes(node):
                            visit(child, conditions)
                    visit(fn)
    rows = [dict(field=field, initial="; ".join(sorted(ref["init"])), writes="; ".join(sorted(ref["write"])), reads="; ".join(sorted(ref["read"]))) for field, ref in sorted(refs.items()) if ref["write"] or ref["init"]]
    write_csv("state_references.csv", rows, ["field", "initial", "writes", "reads"])
    write_csv("reset_assignments.csv", resets, ["file", "function", "line", "field", "value"])
    write_csv("main_line_returns.csv", returns, ["file", "line", "conditions", "preceding"])
    runtime = [dict(method=name, runtime_line=line, core_line=methods["mediator.py"].get(name, ""), kind="override" if name in methods["mediator.py"] else "runtime_helper") for name, line in methods["runtime_mediator.py"].items()]
    write_csv("runtime_method_inventory.csv", runtime, ["method", "runtime_line", "core_line", "kind"])
    # Review annotations for candidate f4c847c; raw AST references above remain
    # useful after edits, but these line groups must be reviewed after rebasing.
    groups = [
        (13673, "整局截止", "round deadline", "QUIT；先于聊天/压力等可重复输入"),
        (13685, "战后总预算", "固定300s，不因输入成功续期", "QUIT并记录TIMEOUT"),
        (13781, "传家宝等待", "广场60s/未知120s", "QUIT；instance锁存后等待自身结算"),
        (13793, "玩家确认/跟车秘境等待", "监督180s或整局截止", "game_round仅软复位；其他可升级QUIT"),
        (13799, "失败奖励关闭", "战后总预算300s", "重复成功点击不续期总预算"),
        (13835, "游戏难度/误开选关", "阶段切换", "ROOM_WAITING(600s)/QUIT(240s)"),
        (13863, "战后背包关闭", "FSM关闭5s；战后总预算300s", "关闭失败可重试；总预算不可续期"),
        (13903, "存档/HUD连续证据", "2个不同帧；战后总预算300s", "确认后路线推进"),
        (13929, "未验证archive", "战后总预算300s", "按world软复位/退出"),
        (13959, "传家宝后胜利", "当前tick", "hitch转QUIT"),
        (14023, "胜利继续", "30s/3次重试；战后总预算300s", "成功点击不续期总预算"),
        (14108, "存档处理/关闭", "Boss局部预算；战后总预算300s", "转heirloom或继续等待"),
        (14200, "NPC请求与路线", "active等3s后重发；战后总预算300s", "路线推进/QUIT"),
        (14268, "传家宝面板", "按页重置Boss预算；战后总预算300s", "关框后武装60/120s观察"),
        (14316, "大秘境确认", "请求3-15s/3次；取消3次", "观察入境或ERROR；正常hitch不主动请求"),
        (14336, "未知战后/传家宝入口", "战后总预算300s", "按world升级；发送入口不代表到达"),
        (14414, "表面冲突", "2.5s可信降级；panel deadline", "监督/整局截止"),
        (14448, "强制词缀/进化选择", "局部节流/后置窗口", "确认后推进；正常hitch不主动进化"),
        (14462, "未知仲裁表面", "监督180s或整局截止", "软复位或退出"),
        (14504, "未验证archive", "战后总预算300s", "软复位或退出"),
        (14530, "继续后未知转场", "战后总预算300s", "game_round只软复位；其它可升级退出"),
        (14550, "选关保护", "当前tick", "STAGE_SELECT；正常hitch已前置QUIT"),
        (14563, "自动任务门禁", "helper复查；监督180s", "确认后下行"),
        (14603, "开局保护", "20s", "继续局内循环"),
        (14687, "主动循环/进化", "步进或3次反馈预算/冷却", "推进环；solo分支非正常hitch"),
        (14701, "公共背包", "5/6/4/5s事务+30s租期", "完成/中止/节流；下一循环"),
        (14726, "拾取", "节流或直接步进", "hitch转public_bag；不使用个人资产"),
        (14749, "黑商", "发现10s；FSM后置", "无可买则转下一步"),
        (14758, "循环idle", "15s状态步进；180s监督", "只软复位或round deadline"),
    ]
    ownership = []
    for row in returns:
        if row["file"] == "runtime_mediator.py":
            owner, bound, destination = "LIVE遥测", "15s", "Core已运行；不注入输入"
        else:
            match = next((g for g in groups if row["line"] <= g[0]), None)
            if match is None:
                owner, bound, destination = "审查后新增返回点", "待人工复核", "见源码条件"
            else:
                _, owner, bound, destination = match
        ownership.append(dict(file=row["file"], line=row["line"], owner=owner, bound=bound, destination=destination, conditions=row["conditions"], input_note="可能零输入的保守超集；条件及前文见main_line_returns.csv"))
    write_csv("main_line_return_ownership.csv", ownership, ["file", "line", "owner", "bound", "destination", "conditions", "input_note"])
    print(f"static: {len(rows)} fields, {len(returns)} literal Continue sites", flush=True)


def frame_matrix():
    import cv2
    import numpy as np
    from shuabao.runtime_mediator import Mediator
    from shuabao.settings import Settings
    from shuabao.vision.capture import Frame

    cv2.setNumThreads(1)
    paths = sorted(p for base in (ROOT / "tests/fixtures", ROOT / "fixtures") for p in base.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"})
    fields = ["path", "sha256", "width", "height", "status", "context", "post_game", "hud", "host_wait", "top_bar", "exit_confirm", "chat", "room", "conflicts", "error"]
    med = Mediator(Settings(mode_id="lobby_hitch", ocr_mode="off", dry_run=True), ROOT)
    cache = {}
    with (OUT / "classifier_matrix.csv").open("w", newline="", encoding="utf-8-sig") as stream, open(os.devnull, "w") as sink:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for i, path in enumerate(paths):
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest not in cache:
                img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    cache[digest] = [dict(status="decode_failed")]
                else:
                    h, w = img.shape[:2]
                    med._ui_scale = round(min(w / 1600.0, h / 900.0, 1.0), 3) if w >= 200 and h >= 200 else 1.0
                    results = []
                    for context, pending, route in (("fresh", False, "secret"), ("archive_pending", True, "archive"), ("boss_active", False, "boss_active")):
                        row = dict(width=w, height=h, status="classified" if w >= 480 and h >= 270 else "crop_or_small", context=context)
                        med.invalidate_evidence("matrix-context")
                        med._post_game_pending = pending
                        med._post_game_route = route
                        med._post_game_archive_pending_only = False
                        # Both independent visual families run; the game-specific
                        # classifiers get a game title instead of silently returning
                        # False due to missing captured-window metadata.
                        frame = Frame(img, hwnd=7, window_title="英雄三国", role="l1")
                        med._ensure_evidence(frame)
                        try:
                            with contextlib.redirect_stdout(sink):
                                row.update(post_game=med._post_game_state(frame), hud=med._is_in_game_hud(frame), host_wait=med._host_choosing_difficulty(frame), top_bar=med._top_bar_mode(frame), exit_confirm=med._find_exit_confirm(frame) is not None, chat=med._game_chat_input_visible(frame), room=med._hitch_room_surface_evidence(frame) is not None)
                            conflicts = []
                            if row["host_wait"] and row["hud"]:
                                conflicts.append("host_wait+hud")
                            if row["room"] and (row["hud"] or row["post_game"] or row["host_wait"]):
                                conflicts.append("room+game")
                            if row["exit_confirm"] and row["post_game"] == "GREAT_RIFT_CONFIRM":
                                conflicts.append("exit+rift")
                            # HUD may legitimately be visible below a foreground
                            # modal; record as overlap, not an exclusive error.
                            row["conflicts"] = ";".join(conflicts)
                        except Exception as exc:
                            row.update(status="error", error=f"{type(exc).__name__}: {exc}")
                        results.append(row)
                    cache[digest] = results
            for row in cache[digest]:
                writer.writerow(dict(path=path.relative_to(ROOT).as_posix(), sha256=digest, **row))
            stream.flush()
            if (i+1) % 25 == 0:
                print(f"matrix: {i+1}/{len(paths)} images ({len(cache)} unique)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", action="store_true")
    parser.add_argument("--frames", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.static:
        static_inventory()
    if args.frames:
        frame_matrix()
