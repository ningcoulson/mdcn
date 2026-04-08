from __future__ import annotations

from datetime import date

from mdcn2.domain.models import MetadataResult
from mdcn2.pipeline.metadata import MetadataPipeline


def test_metadata_pipeline_normalizes_whitespace_and_dedupes():
    pipeline = MetadataPipeline()
    result = MetadataResult(
        number=" md-001 ",
        title="  激情   序幕 ",
        outline="  简介  ",
        actors=["林可菲", "林可菲", " 苏语堂 "],
        tags=["原创", "原创", " 都市 "],
        release_date=date(2024, 8, 15),
    )

    normalized = pipeline.normalize(result)

    assert normalized.number == "MD-001"
    assert normalized.title == "激情 序幕"
    assert normalized.outline == "简介"
    assert normalized.actors == ["林可菲", "苏语堂"]
    assert normalized.tags == ["原创", "都市"]
    assert normalized.year == 2024
