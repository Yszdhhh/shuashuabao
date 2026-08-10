"""B2-3 词典归一化（纯函数）。

本模块只做三件事：
1. ``normalize_choice_text``：Unicode NFKC → 去装饰符/多余空白 → 规范化串；
2. ``lookup_lexicon``：精确别名匹配 → 受限模糊匹配，返回第一/第二候选与分差；
3. ``load_lexicon`` / ``lexicon_errors``：加载并校验 ``config/choice_lexicon.json``。

安全不变量（与蓝图 B2-3 / §3 一致）：
- 不导入 paddle / 不截图 / 不访问窗口，不提供任何坐标；
- 词典未知项只返回 ``canonical=None``，由调用方决定是否留 incident；
- 本模块绝不写回生产词典（无任何写入路径）；
- 分差不足时不硬猜：返回 ``None``。

输入文本来自调用方已经裁剪好的固定 ROI，本模块不负责裁剪。
"""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

LEXICON_PATH = Path(__file__).resolve().parents[3] / "config" / "choice_lexicon.json"

VALID_KINDS = frozenset({"skill", "bond", "treasure"})

# 模糊匹配的默认分差阈值；低于该值返回 None，不硬猜。
DEFAULT_MARGIN_THRESHOLD = 0.15

# 模糊候选绝对下限：低于该相似度即使分差足够也不接受（防止无关词误命中）。
_FUZZY_FLOOR = 0.6

# 装饰符：游戏里出现的 [新]/[NEW]/（新）角标与星星，OCR 常把角标带进文本。
_DECORATOR_RE = re.compile(
    r"\[[^\]\[]*?(?:新|NEW|新技能)[^\]\[]*?\]"
    r"|[（(][^()（）]*?(?:新|NEW|新技能)[^()（）]*?[）)]",
    re.IGNORECASE,
)
_STAR_RE = re.compile(r"[★☆✦✧]+")
_WS_RE = re.compile(r"\s+")

# 常见 OCR 混淆替换表（受限模糊匹配时对两侧文本做等价化）。
# 全角→半角已由 NFKC 覆盖；这里只放 NFKC 不处理的字符级混淆。
_OCR_CONFUSION_REPLACEMENTS = {
    "＊": "*",
    "·": "・",
}


class LexiconMatch(NamedTuple):
    """一次词典查找的结果。可作为 ``(canonical, top2_names, margin)`` 三元组解包。"""

    canonical: str | None
    top2_names: tuple[str, ...]
    margin: float


def normalize_choice_text(raw: str) -> str:
    """Unicode NFKC → 去装饰符/多余空白 → 返回规范化串。

    - NFKC：全角数字/字母/空格转半角（如 ``４星球`` → ``4星球``）；
    - 去掉 ``[新]`` / ``[NEW]`` / ``（新）`` 角标与 ``★☆`` 装饰；
    - 去掉全部空白：中文规范名不含内部空格，OCR 插入的空格一律清除
      （``"剑 气"`` → ``"剑气"``，``" 天雷[NEW] "`` → ``"天雷"``）。
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = _DECORATOR_RE.sub("", text)
    text = _STAR_RE.sub("", text)
    text = _WS_RE.sub("", text)
    return text


def lexicon_errors(data: Any) -> list[str]:
    """校验词典数据结构，返回错误列表；空列表表示通过。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["lexicon must be a JSON object"]
    if not isinstance(data.get("version"), str) or not data["version"]:
        errors.append("missing non-empty 'version'")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return errors + ["missing 'entries' object"]
    surfaces: dict[str, str] = {}
    for canonical, entry in entries.items():
        if not isinstance(canonical, str) or not canonical.strip():
            errors.append("canonical name must be a non-empty string")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{canonical}: entry must be an object")
            continue
        kind = entry.get("kind")
        if kind not in VALID_KINDS:
            errors.append(
                f"{canonical}: kind={kind!r} not in {sorted(VALID_KINDS)}"
            )
        for field in ("aliases", "confusions"):
            value = entry.get(field)
            if not isinstance(value, list) or not all(
                isinstance(s, str) for s in value
            ):
                errors.append(f"{canonical}: {field} must be a list of strings")
        version_seen = entry.get("version_seen")
        if not isinstance(version_seen, str) or not version_seen:
            errors.append(f"{canonical}: version_seen must be a non-empty string")
        set_membership = entry.get("set_membership")
        if set_membership is not None and not isinstance(set_membership, str):
            errors.append(f"{canonical}: set_membership must be string or null")
        for surface in (canonical, *entry.get("aliases", [])):
            key = normalize_choice_text(surface)
            if not key:
                errors.append(f"{canonical}: empty surface {surface!r}")
                continue
            if key in surfaces and surfaces[key] != canonical:
                errors.append(
                    f"{canonical}: surface {surface!r} collides with {surfaces[key]}"
                )
            surfaces[key] = canonical
    return errors


@lru_cache(maxsize=1)
def load_lexicon(path: str | Path | None = None) -> dict[str, Any]:
    """加载并校验 ``config/choice_lexicon.json``（结果缓存；无网络依赖）。

    校验失败抛 ``ValueError``，避免带病词典参与决策。
    """
    p = Path(path) if path is not None else LEXICON_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    errors = lexicon_errors(data)
    if errors:
        raise ValueError("choice_lexicon.json invalid: " + "; ".join(errors))
    return data


def _apply_replacements(text: str) -> str:
    for variant, standard in _OCR_CONFUSION_REPLACEMENTS.items():
        text = text.replace(variant, standard)
    return text


def _similarity(text: str, surface: str) -> float:
    """受限模糊相似度：[0, 1]。

    - 相等 → 1.0；
    - 一方完整包含另一方（前缀/后缀共享，如 ``射线`` ⊂ ``射线增幅``）
      → ``0.5 + 0.5 * 短/长``，让截断前缀与完整词保持可区分；
    - 其余用 ``difflib.SequenceMatcher`` 比率。
    """
    if text == surface:
        return 1.0
    if not text or not surface:
        return 0.0
    best = SequenceMatcher(None, text, surface).ratio()
    if len(text) >= 2 and len(surface) >= 2:
        if text in surface or surface in text:
            short, long = (text, surface) if len(text) <= len(surface) else (surface, text)
            best = max(best, 0.5 + 0.5 * len(short) / len(long))
    return best


def _score_entry(text: str, canonical: str, entry: dict[str, Any]) -> float:
    """单个词条的最佳得分：先精确别名，再对规范化后的别名/规范名做受限模糊。"""
    surfaces = (canonical, *entry.get("aliases", []))
    normalized_surfaces = tuple(
        _apply_replacements(normalize_choice_text(s)) for s in surfaces
    )
    if text in normalized_surfaces:
        return 1.0
    return max((_similarity(text, s) for s in normalized_surfaces), default=0.0)


def lookup_lexicon(
    text: str,
    kind: str | None = None,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
    lexicon: dict[str, Any] | None = None,
) -> LexiconMatch:
    """把 OCR 文本映射到规范名，返回 ``(canonical, top2_names, margin)``。

    - ``kind`` 限定词条类别（skill/bond/treasure），``None`` 表示全类别；
    - 先精确别名匹配（命中即返回，不被模糊分差否决）；
    - 无精确命中时做受限模糊匹配，第一/第二候选分差低于
      ``margin_threshold``（默认 0.15）或最强候选低于绝对下限时返回
      ``canonical=None`` —— 不硬猜；
    - 词典未知项：``canonical=None``，调用方保留原文留 incident；
      本函数绝不写回词典，也不修改传入的 ``lexicon``。
    """
    if kind is not None and kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_KINDS)} or None")
    normalized = normalize_choice_text(text)
    if not normalized:
        return LexiconMatch(None, (), 0.0)
    data = lexicon if lexicon is not None else load_lexicon()
    entries = data.get("entries", {})
    scored: list[tuple[float, str]] = []
    for canonical, entry in entries.items():
        if kind is not None and entry.get("kind") != kind:
            continue
        score = _score_entry(normalized, canonical, entry)
        if score > 0.0:
            scored.append((score, canonical))
    if not scored:
        return LexiconMatch(None, (), 0.0)
    # 按得分降序；同分按规范名字典序，保证确定性。
    scored.sort(key=lambda item: (-item[0], item[1]))
    top1_score, top1_name = scored[0]
    top2_score = scored[1][0] if len(scored) > 1 else 0.0
    margin = top1_score - top2_score
    top2_names = tuple(canonical for _, canonical in scored[:2])
    is_exact = top1_score >= 1.0
    if not is_exact and (top1_score < _FUZZY_FLOOR or margin < margin_threshold):
        return LexiconMatch(None, top2_names, margin)
    return LexiconMatch(top1_name, top2_names, margin)
