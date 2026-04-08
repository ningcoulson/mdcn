"""Typed configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class PathsConfig:
    source_dir: Path
    target_root: Path


@dataclass(slots=True)
class OutputConfig:
    max_images: int = 6
    write_nfo: bool = True
    write_json: bool = True
    folder_template: str = "{number} {title}"


@dataclass(slots=True)
class NetworkConfig:
    proxy: str | None = None
    timeout: float = 20.0
    retries: int = 2


@dataclass(slots=True)
class ScannerConfig:
    extensions: tuple[str, ...] = (".mp4", ".mkv", ".avi", ".ts", ".mov", ".wmv", ".flv")

    def normalized_extensions(self) -> set[str]:
        return {ext.lower() for ext in self.extensions}


@dataclass(slots=True)
class SiteConfig:
    enabled: bool = True
    base_url: str = ""
    mirrors: tuple[str, ...] = ()


@dataclass(slots=True)
class PriorityConfig:
    site_order: tuple[str, ...] = ()


@dataclass(slots=True)
class AppConfig:
    paths: PathsConfig
    output: OutputConfig = field(default_factory=OutputConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    priority: PriorityConfig = field(default_factory=PriorityConfig)
    sites: dict[str, SiteConfig] = field(default_factory=dict)
