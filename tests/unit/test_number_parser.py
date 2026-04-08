from __future__ import annotations

from mdcn2.scanner.number_parser import extract_candidates, normalize_filename, normalize_number


def test_normalize_filename_cleans_common_symbols():
    text = "【MD-96】演示_样片.part1"
    assert normalize_filename(text) == "MD-96 演示 样片 part1"


def test_normalize_number_pads_digits_and_removes_disc_suffix():
    assert normalize_number("md-96_cd1") == "MD-096"
    assert normalize_number("91cm016") == "91CM-016"


def test_extract_candidates_returns_dashed_and_compact_forms():
    candidates = extract_candidates("【91CM-16】东京街头搭讪")
    normalized = [candidate.normalized for candidate in candidates]
    assert normalized[:2] == ["91CM-016", "91CM016"]


def test_extract_candidates_handles_compact_tokens():
    candidates = extract_candidates("MDX0046 人生大赢家")
    normalized = [candidate.normalized for candidate in candidates]
    assert "MDX-0046" in normalized
    assert "MDX0046" in normalized
