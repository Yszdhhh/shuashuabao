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


def test_hitch_prefix_accepts_strict_forms():
    from shuabao.lobby_hitch import has_prefix_evidence

    assert has_prefix_evidence("3", "3")
    assert has_prefix_evidence("３", "３")
    assert has_prefix_evidence("3", "３")
    assert has_prefix_evidence("３", "3")
    assert has_prefix_evidence("3/4", "3")
    assert has_prefix_evidence(" 3 / 4 ", "3")
    assert has_prefix_evidence("3-4", "3")
    assert has_prefix_evidence("3－4", "3")
    assert has_prefix_evidence("３／４", "3")
    assert has_prefix_evidence("3—4", "3")
    assert has_prefix_evidence("３—４", "3")


def test_hitch_prefix_rejects_malformed_and_trailing_text():
    from shuabao.lobby_hitch import has_prefix_evidence

    assert not has_prefix_evidence("3/", "3")
    assert not has_prefix_evidence("3//4", "3")
    assert not has_prefix_evidence("3/4/", "3")
    assert not has_prefix_evidence("3/-4", "3")
    assert not has_prefix_evidence("3—-4", "3")
    assert not has_prefix_evidence("3—", "3")
    assert not has_prefix_evidence("3房间", "3")
    assert not has_prefix_evidence("", "3")
    assert not has_prefix_evidence("4/8", "3")


def test_hitch_prefix_rejects_overlong_expected_before_truncation():
    from shuabao.lobby_hitch import has_prefix_evidence

    # normalize_prefix 会截断到 64；超长期望词必须在截断前就被拒绝。
    assert not has_prefix_evidence("3" * 64, "3" * 65)


def test_hitch_prefix_numeric_branch_uses_typed_helper(monkeypatch):
    from shuabao import lobby_hitch

    calls = []

    def _spy(text, expected, *, allowed_chars=None, max_length=None):
        calls.append((text, expected, allowed_chars, max_length))
        return True

    monkeypatch.setattr(lobby_hitch, "verify_expected_text", _spy)
    assert lobby_hitch.has_prefix_evidence("3", "3")
    assert calls, "numeric-prefix branch must route through verify_expected_text"
    text, expected, allowed_chars, _max_length = calls[0]
    assert expected == "3"
    assert allowed_chars == lobby_hitch.NUMERIC_ALPHABET
