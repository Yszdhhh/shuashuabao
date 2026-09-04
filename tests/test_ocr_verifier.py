# -*- coding: utf-8 -*-
"""Task 1 (Stage 1) — typed OCR expected-value validation helper.

Red-first tests: shuabao.vision.ocr_verifier 不存在时本文件收集即失败。
Reviewer regression: has_prefix_evidence 必须放行占据比形式 3/4（含
全角分隔符 NFKC 归一化），同时继续拒绝 3房间 等非数值噪声。
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


def test_expected_text_accepts_occupancy_separator_in_alphabet():
    assert verify_expected_text("3/4", "3", allowed_chars="0123456789/")


def test_counter_parses_bounded_pair_with_whitespace():
    assert parse_counter(" 3 / 4 ") == (3, 4)


def test_counter_rejects_negative_input():
    assert parse_counter("-3/4") is None
    assert parse_counter("3/-4") is None


def test_counter_rejects_overlong_input():
    assert parse_counter("3/" + "9" * 64) is None
    assert parse_counter("9" * 65 + "/4") is None


def test_counter_denominator_mismatch_returns_none():
    assert parse_counter("3/5", denominator=4) is None


def test_counter_incomplete_returns_none():
    assert parse_counter("3/", denominator=4) is None


def test_hitch_prefix_accepts_occupancy_form():
    from shuabao.lobby_hitch import has_prefix_evidence

    assert has_prefix_evidence("3/4", "3")
    assert has_prefix_evidence(" 3 / 4 ", "3")
    assert has_prefix_evidence("3-4", "3")
    assert has_prefix_evidence("3－4", "3")


def test_hitch_prefix_rejects_non_numeric_noise():
    from shuabao.lobby_hitch import has_prefix_evidence

    assert not has_prefix_evidence("3房间", "3")
    assert not has_prefix_evidence("", "3")
    assert not has_prefix_evidence("4/8", "3")
