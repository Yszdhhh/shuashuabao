# -*- coding: utf-8 -*-
"""Task 1 (Stage 1) — typed OCR expected-value validation helper.

Red-first tests: shuabao.vision.ocr_verifier 不存在时本文件收集即失败。
"""

from shuabao.vision.ocr_verifier import parse_counter, verify_expected_text


def test_expected_text_accepts_numeric_match():
    assert verify_expected_text("3", "3", allowed_chars="0123456789")


def test_expected_text_rejects_disallowed_ocr_noise():
    assert not verify_expected_text("3房间", "3", allowed_chars="0123456789")


def test_expected_text_rejects_empty_expected():
    assert not verify_expected_text("3", "", allowed_chars="0123456789")


def test_expected_text_rejects_empty_input():
    assert not verify_expected_text("", "3", allowed_chars="0123456789")


def test_counter_parses_bounded_pair_with_whitespace():
    assert parse_counter(" 3 / 4 ") == (3, 4)


def test_counter_denominator_mismatch_returns_none():
    assert parse_counter("3/5", denominator=4) is None


def test_counter_incomplete_returns_none():
    assert parse_counter("3/", denominator=4) is None
