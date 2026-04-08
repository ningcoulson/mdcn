"""Directory scanning."""

from __future__ import annotations

from pathlib import Path

from mdcn.domain.models import VideoFile


def iter_video_files(root: Path, extensions: set[str]) -> list[VideoFile]:
    files: list[VideoFile] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if path.name.startswith("."):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue
        stat = path.stat()
        files.append(
            VideoFile(
                path=path,
                stem=path.stem,
                extension=path.suffix.lower(),
                size=stat.st_size,
            )
        )
    return files
