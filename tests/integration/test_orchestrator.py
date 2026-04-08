from __future__ import annotations

from pathlib import Path

import pytest

from mdcn2.config.models import AppConfig, NetworkConfig, OutputConfig, PathsConfig, ScannerConfig, SiteConfig
from mdcn2.crawlers.base import BaseCrawler
from mdcn2.crawlers.registry import CrawlerRegistry
from mdcn2.domain.models import MetadataResult, NumberCandidate
from mdcn2.pipeline.metadata import MetadataPipeline
from mdcn2.pipeline.orchestrator import ScrapeOrchestrator
from mdcn2.pipeline.organizer import FileOrganizer
from mdcn2.pipeline.resources import ResourcePipeline
from mdcn2.pipeline.writer import OutputWriter
from mdcn2.storage.task_repo import TaskRepository


class FakeCrawler(BaseCrawler):
    @property
    def name(self) -> str:
        return "fake"

    @property
    def default_base_url(self) -> str:
        return "https://example.com"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        return "https://example.com/detail"

    async def fetch(self, url: str) -> str:
        return "<html></html>"

    async def parse(self, html: str, url: str, candidate: NumberCandidate, *, file_hint: str = "") -> MetadataResult:
        return MetadataResult(number=candidate.normalized, title="示例标题")


@pytest.mark.asyncio
async def test_orchestrator_processes_video_end_to_end(tmp_path: Path):
    source_dir = tmp_path / "failed"
    target_root = tmp_path / "library"
    source_dir.mkdir()
    target_root.mkdir()
    video_path = source_dir / "MD001.mp4"
    video_path.write_bytes(b"video")

    config = AppConfig(
        paths=PathsConfig(source_dir=source_dir, target_root=target_root),
        output=OutputConfig(write_nfo=True, write_json=True),
        network=NetworkConfig(),
        scanner=ScannerConfig(extensions=(".mp4",)),
        sites={"fake": SiteConfig(enabled=True, base_url="https://example.com")},
    )

    orchestrator = ScrapeOrchestrator(
        config=config,
        registry=CrawlerRegistry([FakeCrawler()]),
        metadata_pipeline=MetadataPipeline(),
        resource_pipeline=ResourcePipeline(max_images=0),
        writer=OutputWriter(),
        organizer=FileOrganizer(),
        task_repo=TaskRepository(target_root / ".mdcn2" / "tasks.db"),
    )

    stats = await orchestrator.run()

    assert stats.scanned == 1
    assert stats.succeeded == 1
    output_dir = target_root / "MD-001 示例标题"
    assert output_dir.exists()
    assert (output_dir / "MD001.mp4").exists()
    assert (output_dir / "metadata.json").exists()
    assert (output_dir / "MD-001.nfo").exists()
