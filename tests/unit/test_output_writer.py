from __future__ import annotations

from datetime import date
from pathlib import Path

from mdcn.domain.models import MetadataResult
from mdcn.pipeline.writer import OutputWriter


def test_output_writer_writes_json_and_nfo(tmp_path: Path):
    writer = OutputWriter()
    result = MetadataResult(
        number="MD-001",
        title="激情序幕",
        actors=["林可菲"],
        release_date=date(2024, 8, 15),
        year=2024,
    )

    json_path = writer.write_metadata_json(result, tmp_path)
    nfo_path = writer.write_nfo(result, tmp_path)

    assert json_path.name == "metadata.json"
    assert '"number": "MD-001"' in json_path.read_text(encoding="utf-8")
    assert nfo_path.name == "MD-001.nfo"
    assert "<title>激情序幕</title>" in nfo_path.read_text(encoding="utf-8")
