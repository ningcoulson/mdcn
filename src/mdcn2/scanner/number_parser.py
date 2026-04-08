"""Filename-to-number candidate extraction."""

from __future__ import annotations

import re

from mdcn2.domain.models import NumberCandidate

_TRAILING_DISC_RE = re.compile(r"(?i)(?:[-_ ]?)(CD|DISC|PART)[-_ ]?\d+$")
_DELIMITED_RE = re.compile(r"([A-Za-z0-9]+-[A-Za-z0-9]+)")
_COMPACT_RE = re.compile(r"([A-Za-z0-9]*?[A-Za-z][A-Za-z0-9]*?)(\d{2,5})$")


def normalize_filename(text: str) -> str:
    value = text
    for old, new in {
        "【": " ",
        "】": " ",
        "[": " ",
        "]": " ",
        "(": " ",
        ")": " ",
        "_": " ",
        ".": " ",
    }.items():
        value = value.replace(old, new)
    value = re.sub(r"[。！？·、，,;:]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_number(token: str) -> str:
    value = token.upper().strip()
    value = _TRAILING_DISC_RE.sub("", value)
    value = value.replace("_", "-")
    value = re.sub(r"[^0-9A-Z-]", "", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        return ""

    if "-" not in value:
        match = _COMPACT_RE.fullmatch(value)
        if match:
            prefix, digits = match.groups()
            padded = digits.zfill(max(3, len(digits)))
            return f"{prefix}-{padded}"
        return value

    head, tail = value.split("-", 1)
    if tail.isdigit():
        tail = tail.zfill(max(3, len(tail)))
    return f"{head}-{tail}"


def extract_candidates(filename_stem: str) -> list[NumberCandidate]:
    cleaned = normalize_filename(filename_stem)
    tokens = [token for token in re.split(r"[\s/]+", cleaned) if token]

    ordered: list[NumberCandidate] = []
    seen: set[str] = set()

    for token in tokens:
        for match in _DELIMITED_RE.findall(token):
            _append_candidate(ordered, seen, raw=match, normalized=normalize_number(match), score=100)

    for token in tokens:
        compact = re.sub(r"[^0-9A-Za-z]", "", token)
        if not compact:
            continue
        match = _COMPACT_RE.fullmatch(compact)
        if match and len(match.group(2)) >= 2:
            normalized = normalize_number(compact)
            _append_candidate(ordered, seen, raw=compact, normalized=normalized, score=90)

    expanded: list[NumberCandidate] = []
    emitted: set[str] = set()
    for candidate in ordered:
        if candidate.normalized not in emitted:
            emitted.add(candidate.normalized)
            expanded.append(candidate)
        compact = candidate.normalized.replace("-", "")
        if compact not in emitted:
            emitted.add(compact)
            expanded.append(NumberCandidate(raw=candidate.raw, normalized=compact, score=candidate.score - 5))

    return expanded


def _append_candidate(
    ordered: list[NumberCandidate],
    seen: set[str],
    *,
    raw: str,
    normalized: str,
    score: int,
) -> None:
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    ordered.append(NumberCandidate(raw=raw, normalized=normalized, score=score))
