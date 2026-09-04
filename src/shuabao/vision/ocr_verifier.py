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

_COUNTER_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


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
    """归一化后校验期望文本是否出现在输入文本中。

    allowed_chars 提供时，输入文本的每个归一化字符都必须在该字母表内；
    输入/期望为空、超长或含越界字符一律返回 False。
    """
    raw = _normalize(text, max_length)
    want = _normalize(expected, max_length)
    if raw is None or want is None:
        return False
    if allowed_chars is not None and any(ch not in allowed_chars for ch in raw):
        return False
    return want in raw


def parse_counter(text: str, *, denominator: int | None = None) -> tuple[int, int] | None:
    """解析有界的 x/y 数值文本；denominator 提供时必须一致，否则 None。"""
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
