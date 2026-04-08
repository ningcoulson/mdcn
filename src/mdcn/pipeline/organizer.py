"""Target directory and file movement helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

from mdcn.domain.models import MetadataResult
from mdcn.output.naming import build_folder_name


class FileOrganizer:
    def build_target_dir(self, result: MetadataResult, target_root: Path) -> Path:
        folder_name = build_folder_name(result.number, result.title)
        return target_root / folder_name

    def move_video(self, source: Path, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / source.name
        if destination.exists():
            destination = target_dir / _generate_unique_name(target_dir, source.name)
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
