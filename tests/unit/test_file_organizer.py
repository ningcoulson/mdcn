from __future__ import annotations

from pathlib import Path

from mdcn.domain.models import MetadataResult
from mdcn.pipeline.organizer import FileOrganizer


def test_file_organizer_builds_target_dir(tmp_path: Path):
    organizer = FileOrganizer()
    result = MetadataResult(number="MD-001", title="激情序幕")

    target_dir = organizer.build_target_dir(result, tmp_path)

    assert target_dir == tmp_path / "MD-001 激情序幕"


def test_file_organizer_moves_file_and_avoids_overwrite(tmp_path: Path):
    organizer = FileOrganizer(folder_template="{studio}/{number} {title}")
    result = MetadataResult(number="MD-001", title="激情序幕", studio="Madou")
    source = tmp_path / "raw_name.mp4"
    source.write_text("a", encoding="utf-8")
    target_dir = tmp_path / "target"
    (target_dir / "MD-001.mp4").parent.mkdir(parents=True, exist_ok=True)
    (target_dir / "MD-001.mp4").write_text("b", encoding="utf-8")

    moved = organizer.move_video(source, target_dir, result)

    assert moved.name == "MD-001_2.mp4"
    assert moved.read_text(encoding="utf-8") == "a"
    assert not source.exists()
