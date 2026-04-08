"""Metadata normalization."""

from __future__ import annotations

from mdcn.domain.models import MetadataResult


class MetadataPipeline:
    def normalize(self, result: MetadataResult) -> MetadataResult:
        result.number = result.number.strip().upper()
        result.title = " ".join(result.title.split()).strip()
        result.outline = result.outline.strip()
        result.actors = _dedupe_strings(result.actors)
        result.tags = _dedupe_strings(result.tags)
        result.studio = result.studio.strip()
        result.publisher = result.publisher.strip()
        result.series = result.series.strip()
        if result.release_date and result.year is None:
            result.year = result.release_date.year
        return result


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split()).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output
