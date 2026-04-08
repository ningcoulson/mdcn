"""Output writing."""

from __future__ import annotations

import json
from pathlib import Path

from mdcn2.domain.models import MetadataResult
from mdcn2.output.json_writer import serialize_metadata
from mdcn2.output.nfo import build_nfo_xml


class OutputWriter:
    def write_metadata_json(self, result: MetadataResult, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "metadata.json"
        path.write_text(
            json.dumps(serialize_metadata(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def write_nfo(self, result: MetadataResult, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{result.number or 'video'}.nfo"
        path = target_dir / filename
        path.write_text(build_nfo_xml(result), encoding="utf-8")
        return path
