from __future__ import annotations

from datetime import date

from mdcn2.domain.models import MetadataResult
from mdcn2.output.nfo import build_nfo_xml


def test_build_nfo_xml_renders_basic_fields():
    result = MetadataResult(
        number="MD-0001",
        title="激情序幕",
        outline="剧情简介",
        actors=["林可菲", "苏语堂"],
        tags=["原创", "都市"],
        studio="麻豆传媒",
        source="madouqu",
        website="https://example.com/detail",
        release_date=date(2024, 8, 15),
        year=2024,
    )

    xml = build_nfo_xml(result)

    assert "<title>激情序幕</title>" in xml
    assert "<id>MD-0001</id>" in xml
    assert "<premiered>2024-08-15</premiered>" in xml
    assert "<tag>原创</tag>" in xml
    assert "<name>林可菲</name>" in xml
