from __future__ import annotations

from pathlib import Path

from mdcn2.scanner.files import iter_video_files


def test_iter_video_files_filters_extensions_and_hidden(tmp_path: Path):
    (tmp_path / "MD-0001.mp4").write_text("a", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("b", encoding="utf-8")
    (tmp_path / ".hidden.mp4").write_text("c", encoding="utf-8")
    (tmp_path / "dir").mkdir()

    files = iter_video_files(tmp_path, {".mp4", ".mkv"})

    assert [item.path.name for item in files] == ["MD-0001.mp4"]
    assert files[0].stem == "MD-0001"
    assert files[0].extension == ".mp4"
    assert files[0].size == 1
