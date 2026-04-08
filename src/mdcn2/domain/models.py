"""Core data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class VideoFile:
    path: Path
    stem: str
    extension: str
    size: int


@dataclass(slots=True)
class NumberCandidate:
    raw: str
    normalized: str
    score: int = 0


@dataclass(slots=True)
class ImageAsset:
    url: str
    kind: str
    local_path: Path | None = None
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MetadataResult:
    number: str
    title: str
    outline: str = ""
    actors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    studio: str = ""
    publisher: str = ""
    series: str = ""
    country: str = "CN"
    release_date: date | None = None
    year: int | None = None
    website: str = ""
    source: str = ""
    images: list[ImageAsset] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScrapeTask:
    video: VideoFile
    candidates: list[NumberCandidate] = field(default_factory=list)
