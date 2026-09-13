# -*- coding: utf-8 -*-
"""类型化 OCR 期望值校验助手（Stage 1 Task 1）。

只依赖标准库：对有界文本做 NFKC 归一化后按字母表/数值语义校验，
任何验证失败一律返回 False/None（fail-closed）。
"""

from __future__ import annotations

import re
import unicodedata

MAX_LENGTH = 64
NUMERIC_ALPHABET = "0123456789"

_COUNTER_RE = re.compile(r"(\d+)\s*[/\-—]\s*(\d+)")


def _normalize(text: object, max_length: int) -> str | None:
    """NFKC 归一化并去除首尾空白；空或超长返回 None（fail-closed）。"""
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not value or len(value) > max_length:
        return None
    return value


def verify_expected_text(
    text: str,
    expected: str,
    *,
    allowed_chars: str | None = None,
    max_length: int = MAX_LENGTH,
) -> bool:
    """验证归一化文本与期望值完全相等。

    期望值与输入均须非空且有界；提供 allowed_chars 时，双方每个归一化
    字符都必须在该字母表内。所有失败路径均返回 False。
    """
    raw = _normalize(text, max_length)
    want = _normalize(expected, max_length)
    if raw is None or want is None:
        return False
    if allowed_chars is not None:
        if any(ch not in allowed_chars for ch in raw):
            return False
        if any(ch not in allowed_chars for ch in want):
            return False
    return raw == want


def parse_counter(text: str, *, denominator: int | None = None) -> tuple[int, int] | None:
    """解析有界的 x/y、x-y 或 x—y 数值文本；分母提供时必须一致。"""
    raw = _normalize(text, MAX_LENGTH)
    if raw is None:
        return None
    match = _COUNTER_RE.fullmatch(raw)
    if match is None:
        return None
    numerator, actual = int(match.group(1)), int(match.group(2))
    if denominator is not None and actual != denominator:
        return None
    return (numerator, actual)
