# -*- coding: utf-8 -*-
"""Task 1 (Stage 1) — typed OCR expected-value validation helper."""

from shuabao.vision.ocr_verifier import parse_counter, verify_expected_text


def test_expected_text_accepts_exact_numeric_match():
    assert verify_expected_text("3", "3", allowed_chars="0123456789")
    assert verify_expected_text("44", "44", allowed_chars="0123456789")


def test_expected_text_rejects_containment_only_match():
    assert not verify_expected_text("444", "44", allowed_chars="0123456789")


def test_expected_text_rejects_disallowed_ocr_noise_and_expected():
    assert not verify_expected_text("3房间", "3", allowed_chars="0123456789")
    assert not verify_expected_text("3", "3房间", allowed_chars="0123456789")
    assert not verify_expected_text("3", "3/4", allowed_chars="0123456789")


def test_expected_text_rejects_empty_expected_and_input():
    assert not verify_expected_text("3", "", allowed_chars="0123456789")
    assert not verify_expected_text("3", "   ", allowed_chars="0123456789")
    assert not verify_expected_text("", "3", allowed_chars="0123456789")


def test_expected_text_normalizes_fullwidth_values():
    assert verify_expected_text("３", "３", allowed_chars="0123456789")


def test_expected_text_rejects_overlong_values():
    assert not verify_expected_text("3" * 65, "3" * 65, allowed_chars="0123456789")
    assert not verify_expected_text("3" * 64, "3" * 65, allowed_chars="0123456789")


def test_counter_parses_bounded_pair_with_whitespace_and_separators():
    assert parse_counter(" 3 / 4 ") == (3, 4)
    assert parse_counter("3-4") == (3, 4)
    assert parse_counter("３—４") == (3, 4)


def test_counter_rejects_negative_malformed_and_overlong_input():
    assert parse_counter("-3/4") is None
    assert parse_counter("3/-4") is None
    assert parse_counter("3/") is None
    assert parse_counter("3//4") is None
    assert parse_counter("3/4 room") is None
    assert parse_counter("3/" + "9" * 64) is None


def test_counter_denominator_mismatch_returns_none():
    assert parse_counter("3/5", denominator=4) is None


def test_hitch_prefix_accepts_cleaned_occupancy_and_exact_forms():
    from shuabao.lobby_hitch import has_prefix_evidence

    assert has_prefix_evidence("3", "3")
    assert has_prefix_evidence("３", "３")
    assert has_prefix_evidence("3/4", "3")
    assert has_prefix_evidence(" 3 / 4 ", "3")
    assert has_prefix_evidence("3-4", "3")
    assert has_prefix_evidence("３—４", "3")
    assert has_prefix_evidence("44", "44")


def test_hitch_prefix_accepts_exact_unicode_search_term():
    from shuabao.lobby_hitch import has_prefix_evidence

    assert has_prefix_evidence("速", "速")
    assert not has_prefix_evidence("极速", "速")
    assert has_prefix_evidence("2-7", "2-7")
    assert has_prefix_evidence("2 - 7", "2-7")
    assert has_prefix_evidence("3—4", "3-4")
    assert not has_prefix_evidence("2-8", "2-7")


def test_hitch_prefix_rejects_malformed_ambiguous_and_invalid_expected():
    from shuabao.lobby_hitch import has_prefix_evidence

    assert not has_prefix_evidence("444", "44")
    assert not has_prefix_evidence("3/", "3")
    assert not has_prefix_evidence("3//4", "3")
    assert not has_prefix_evidence("3/4/", "3")
    assert not has_prefix_evidence("3/-4", "3")
    assert not has_prefix_evidence("3—-4", "3")
    assert not has_prefix_evidence("3/4 room", "3")
    assert not has_prefix_evidence("3房间", "3")
    assert not has_prefix_evidence("", "3")
    assert not has_prefix_evidence("3", "")
    assert not has_prefix_evidence("3", " ")
    assert not has_prefix_evidence("3", "3" * 65)
    assert not has_prefix_evidence("3", "3房")
    assert not has_prefix_evidence("3", "3/4")


def test_hitch_prefix_numeric_branch_uses_typed_helper(monkeypatch):
    from shuabao import lobby_hitch

    calls = []

    def _spy(text, expected, *, allowed_chars=None, max_length=64):
        calls.append((text, expected, allowed_chars, max_length))
        return True

    monkeypatch.setattr(lobby_hitch, "verify_expected_text", _spy)
    assert lobby_hitch.has_prefix_evidence("3", "3")
    assert calls == [("3", "3", lobby_hitch.NUMERIC_ALPHABET, 64)]


def test_normalize_prefix_preserves_overlong_authority_for_verifier():
    from shuabao.lobby_hitch import has_prefix_evidence, normalize_prefix

    expected = "3" * 65
    assert normalize_prefix(expected) == expected
    assert not has_prefix_evidence("3" * 64, expected)
