from __future__ import annotations

from pathlib import Path

import pytest

from mdcn.config.models import AppConfig, NetworkConfig, OutputConfig, PathsConfig, ScannerConfig, SiteConfig
from mdcn.crawlers.base import BaseCrawler
from mdcn.crawlers.registry import CrawlerRegistry
from mdcn.domain.models import MetadataResult, NumberCandidate
from mdcn.pipeline.metadata import MetadataPipeline
from mdcn.pipeline.orchestrator import ScrapeOrchestrator
from mdcn.pipeline.organizer import FileOrganizer
from mdcn.pipeline.resources import ResourcePipeline
from mdcn.pipeline.writer import OutputWriter
from mdcn.storage.task_repo import TaskRepository


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
        return MetadataResult(number=candidate.normalized, title="示例标题", studio="Madou")


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
        output=OutputConfig(write_nfo=True, write_json=True, folder_template="{studio}/{number} {title}"),
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
        organizer=FileOrganizer(folder_template=config.output.folder_template),
        task_repo=TaskRepository(target_root / ".mdcn" / "tasks.db"),
    )

    stats = await orchestrator.run()

    assert stats.scanned == 1
    assert stats.succeeded == 1
    output_dir = target_root / "Madou" / "MD-001 示例标题"
    assert output_dir.exists()
    assert (output_dir / "MD001.mp4").exists()
    assert (output_dir / "metadata.json").exists()
    assert (output_dir / "MD-001.nfo").exists()


@pytest.mark.asyncio
async def test_orchestrator_retries_failed_tasks(tmp_path: Path):
    source_dir = tmp_path / "failed"
    target_root = tmp_path / "library"
    source_dir.mkdir()
    target_root.mkdir()
    video_path = source_dir / "MD002.mp4"
    video_path.write_bytes(b"video")

    config = AppConfig(
        paths=PathsConfig(source_dir=source_dir, target_root=target_root),
        output=OutputConfig(write_nfo=False, write_json=True),
        network=NetworkConfig(),
        scanner=ScannerConfig(extensions=(".mp4",)),
        sites={"fake": SiteConfig(enabled=True, base_url="https://example.com")},
    )

    task_repo = TaskRepository(target_root / ".mdcn" / "tasks.db")
    task_repo.mark_failure(str(video_path), reason="no_match", detail="temporary")

    orchestrator = ScrapeOrchestrator(
        config=config,
        registry=CrawlerRegistry([FakeCrawler()]),
        metadata_pipeline=MetadataPipeline(),
        resource_pipeline=ResourcePipeline(max_images=0),
        writer=OutputWriter(),
        organizer=FileOrganizer(folder_template=config.output.folder_template),
        task_repo=task_repo,
    )

    stats = await orchestrator.retry_failed()

    assert stats.scanned == 1
    assert stats.succeeded == 1
    assert task_repo.was_processed(str(video_path)) is True
    assert (target_root / "MD-002 示例标题" / "MD002.mp4").exists()
