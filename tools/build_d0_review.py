#!/usr/bin/env python3
"""O2-2: D0 未知槽视觉复核结果合并 + 决策规则落库。

输入：
- fixtures/ocr_choices/D0_extended_manifest.json（D0 候选 manifest）
- fixtures/ocr_choices/review/verdicts/*.json（vision/designer 子 agent 原始复核记录：
  谁=agent id / 何时=session 内 yield 时间 / 依据=crop 图像 / 置信度=confidence）
- config/choice_lexicon.json（现有词典）

输出：
- fixtures/ocr_choices/D0_vision_review.json（机器可读复核记录：逐槽 final 判定）
- 更新 fixtures/ocr_choices/D0_extended_manifest.json（复核后槽位 canonical/unknown 落库）

决策规则（R1-R6，全部机器可复现）：
- R1 名称形态：复核文本为 2-6 个汉字（允许 (中)/(小)/(大) 后缀与 一~七星球 等）→ 名称形态；
  含数字/+/%/属性描述（攻击力+50、生命值+100、在接下来30秒内…）或英文/单字符 → 非名称。
- R2 词典命中：复核文本（规范化后）与词典规范名/别名 **全等** → canonical=该规范名
  （模糊包含命中不算：致残剑气/剑气冲击/风舞者/军团 是独立名称，不得折叠进
  剑气/蛮舞者/巨龙军团）。
- R3 名称确认：R1 且复核 is_card_name=true → canonical=复核文本（新增词典项）。
- R4 其余 → unknown（显式保留）。
- R5 矢/失字形混淆：复核文本以 箭失 开头且对应 箭矢* 词典项存在 → 归一为 箭矢*（游戏名称为 箭矢，矢/失 为同类字形误读）。
- R6 资源物品后缀约定：^（经验|金币|木材|杀敌|攻击|生命)(中|小|大)$ 形态 → canonical treasure
  （与既有 经验(中) 同款命名约定；设计师按“含括号”启发式判 false，以游戏约定为准）。

用法：.venv\\Scripts\\python.exe tools/build_d0_review.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shuabao.vision.choice_ocr import load_lexicon, lookup_lexicon, normalize_choice_text  # noqa: E402

D0_MANIFEST = REPO_ROOT / "fixtures" / "ocr_choices" / "D0_extended_manifest.json"
VERDICTS_DIR = REPO_ROOT / "fixtures" / "ocr_choices" / "review" / "verdicts"
OUT_REVIEW = REPO_ROOT / "fixtures" / "ocr_choices" / "D0_vision_review.json"

# R1: 非名称形态（统计/描述/UI 文本）
_STAT_RE = re.compile(r"\d|[+%]|接下来|攻击力|生命值|暴伤|经验\+|金币\+|杀敌数|物理暴")
_SINGLE_RE = re.compile(r"^[^\u4e00-\u9fff]+$")  # 无汉字
# R6: 资源物品后缀约定
_RESOURCE_SUFFIX_RE = re.compile(r"^(经验|金币|木材|杀敌|攻击|生命)[（(](中|小|大)[）)]$")
# R5: 箭矢 系列（矢/失 混淆）
_ARROW_PATTERNS = ("箭矢增幅", "箭矢连发", "箭矢齐射", "箭矢扩散", "箭矢增幅")


def verdict_text(v: dict) -> str:
    t = (v.get("text") or "").strip()
    if t == "UNREADABLE":
        return ""
    return t


def load_verdicts() -> dict[str, dict]:
    out = {}
    for p in sorted(VERDICTS_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        for v in data.get("verdicts", []):
            vid = v.get("id")
            if vid:
                out[vid] = v
    return out


def decide_slot(slot_text: str, is_card: bool, confidence: float, kind: str, lexicon: dict) -> dict:
    """返回 {decision: canonical|unknown, canonical, kind, rule}。"""
    text = verdict_text({"text": slot_text})
    norm = normalize_choice_text(text)
    # R5: 箭失X → 箭矢X
    if norm.startswith("箭失"):
        for canon in _ARROW_PATTERNS:
            if canon in lexicon["entries"] and canon[2:] == norm[2:]:
                return {"decision": "canonical", "canonical": canon, "kind": lexicon["entries"][canon]["kind"], "rule": "R5"}
    # R6: 资源物品后缀约定
    m = _RESOURCE_SUFFIX_RE.match(norm)
    if m:
        return {"decision": "canonical", "canonical": norm, "kind": "treasure", "rule": "R6"}
    # 非名称形态
    if _STAT_RE.search(norm) or _SINGLE_RE.match(norm) or len(norm) < 2:
        return {"decision": "unknown", "canonical": None, "kind": None, "rule": "R1"}
    # R2: 词典精确命中（规范名或别名 surface 全等；模糊包含命中不算——
    # 例如 致残剑气/剑气冲击/风舞者/军团 是独立名称，不得折叠进 剑气/蛮舞者/巨龙军团）
    if norm:
        for canon, entry in lexicon["entries"].items():
            surfaces = (canon, *entry.get("aliases", []))
            if norm in {normalize_choice_text(s) for s in surfaces}:
                return {"decision": "canonical", "canonical": canon,
                        "kind": entry["kind"], "rule": "R2"}
    # R3: 名称确认
    if is_card and len(norm) >= 2 and confidence >= 0.8:
        return {"decision": "canonical", "canonical": norm, "kind": kind, "rule": "R3"}
    return {"decision": "unknown", "canonical": None, "kind": None, "rule": "R4"}


def main() -> int:
    d0 = json.loads(D0_MANIFEST.read_text(encoding="utf-8"))
    lexicon = load_lexicon()
    verdicts = load_verdicts()
    print(f"verdicts loaded: {len(verdicts)}")

    # sheet index: cell id -> (entry_id, slot_index)
    review_out: dict[str, dict] = {}
    stats = Counter()
    updated = 0
    for e in d0["entries"]:
        for s in e.get("slots", []):
            key = f"{e['id']}|{s['index']}"
            if s.get("is_valid"):
                # 103 canonical 槽：保持 canonical（pending_ocr_confirm），复核记录为 confirmed
                review_out[key] = {
                    "entry_id": e["id"], "slot_index": s["index"],
                    "final": "canonical", "canonical": s.get("canonical_name"),
                    "kind": e["kind"], "basis": "D0 已有 canonical（pending_ocr_confirm，OCR 与词典一致）",
                    "reviewer": "machine", "confidence": 1.0,
                }
                stats["canonical_keep"] += 1
                continue
            # 未知槽：找复核记录
            vid = f"{e['id']}_s{s['index']}"
            v = verdicts.get(vid)
            if v is None:
                # 无 crop 的槽（5 个）：显式 unknown
                review_out[key] = {
                    "entry_id": e["id"], "slot_index": s["index"],
                    "final": "unknown", "canonical": None, "kind": None,
                    "basis": "无 name crop（标注未检测到文本）", "reviewer": "machine",
                    "confidence": 1.0, "rule": "R4",
                }
                s["canonical_name"] = None
                s["annotation_status"] = "reviewed_unknown"
                stats["unknown_nocrop"] += 1
                continue
            text = verdict_text(v)
            dec = decide_slot(text, v.get("is_card_name", False), v.get("confidence", 0.0),
                              e["kind"], lexicon)
            review_out[key] = {
                "entry_id": e["id"], "slot_index": s["index"],
                "final": dec["decision"], "canonical": dec["canonical"],
                "kind": dec["kind"], "rule": dec["rule"],
                "text_visible": text,
                "vision_is_card_name": v.get("is_card_name", False),
                "vision_confidence": v.get("confidence", 0.0),
                "vision_note": v.get("note", ""),
                "basis": f"vision/designer 子 agent 复核 crop 图像（{v.get('note','')}）",
                "reviewer": "gemini-designer",
            }
            stats[dec["decision"] + "_" + dec["rule"]] += 1
            # 落库到 D0 manifest
            s["canonical_name"] = dec["canonical"]
            s["annotation_status"] = "reviewed_canonical" if dec["decision"] == "canonical" else "reviewed_unknown"
            if dec["decision"] == "canonical":
                s["is_valid"] = True
            updated += 1

    review_doc = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "O2-2 D0_extended_manifest 未知槽视觉复核记录（机器可读）",
        "reviewers": ["vision/designer 子 agent（gemini，crop 图像直接视觉阅读）"],
        "rules": {
            "R1": "名称形态过滤（统计/描述/英文/单字符 → 非名称）",
            "R2": "复核文本命中词典（精确/别名）→ canonical=该规范名",
            "R2-anykind": "复核文本跨类别命中词典 → canonical（真理以词典 kind 为准）",
            "R3": "复核 is_card_name=true 且置信度≥0.8 → canonical=复核文本（新增词典项）",
            "R4": "其余显式 unknown",
            "R5": "箭失→箭矢（矢/失 字形混淆，游戏名称为 箭矢*）",
            "R6": "资源物品 (中)/(小)/(大) 后缀 → canonical treasure（经验(中) 同款约定）",
        },
        "slots": review_out,
        "stats": dict(stats),
        "raw_verdicts": str(VERDICTS_DIR),
    }
    OUT_REVIEW.write_text(json.dumps(review_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    D0_MANIFEST.write_text(json.dumps(d0, ensure_ascii=False, indent=1), encoding="utf-8")
    print("review stats:", dict(stats))
    print(f"[OK] {OUT_REVIEW}")
    print(f"[OK] D0 manifest updated ({updated} slots annotated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
