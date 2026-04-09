"""Target directory and file movement helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

from mdcn.domain.models import MetadataResult
from mdcn.output.naming import DEFAULT_FOLDER_TEMPLATE, build_folder_path, build_video_filename


class FileOrganizer:
    def __init__(self, folder_template: str = DEFAULT_FOLDER_TEMPLATE) -> None:
        self.folder_template = folder_template

    def build_target_dir(self, result: MetadataResult, target_root: Path) -> Path:
        folder_path = build_folder_path(
            result.number,
            result.title,
            self.folder_template,
            studio=result.studio,
            series=result.series,
            source=result.source,
            year=result.year,
            actors=result.actors,
        )
        return target_root / folder_path

    def move_video(self, source: Path, target_dir: Path, result: MetadataResult) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        destination_name = build_video_filename(
            result.number,
            result.title,
            source.suffix,
            self.folder_template,
            studio=result.studio,
            series=result.series,
            source=result.source,
            year=result.year,
            actors=result.actors,
        )
        destination = target_dir / destination_name
        if destination.exists():
            destination = target_dir / _generate_unique_name(target_dir, destination_name)
        shutil.move(str(source), destination)
        return destination


def _generate_unique_name(target_dir: Path, filename: str) -> str:
    path = Path(filename)
    stem = path.stem
    suffix = path.suffix
    counter = 2
    candidate = f"{stem}_{counter}{suffix}"
    while (target_dir / candidate).exists():
        counter += 1
        candidate = f"{stem}_{counter}{suffix}"
    return candidate
