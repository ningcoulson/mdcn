"""Runtime wiring."""

from __future__ import annotations

from pathlib import Path

from mdcn2.config.models import AppConfig
from mdcn2.crawlers import CrawlerRegistry, MadouQuCrawler
from mdcn2.crawlers.mdtv import MadouTVCrawler
from mdcn2.pipeline import FileOrganizer, MetadataPipeline, OutputWriter
from mdcn2.pipeline.orchestrator import ScrapeOrchestrator
from mdcn2.pipeline.resources import ResourcePipeline
from mdcn2.storage.task_repo import TaskRepository


def build_orchestrator(config: AppConfig) -> ScrapeOrchestrator:
    crawlers = []
    if config.sites.get("madouqu", None) is None or config.sites["madouqu"].enabled:
        crawlers.append(MadouQuCrawler(base_url=config.sites.get("madouqu").base_url if config.sites.get("madouqu") else None))
    if config.sites.get("mdtv", None) is None or config.sites["mdtv"].enabled:
        crawlers.append(MadouTVCrawler(base_url=config.sites.get("mdtv").base_url if config.sites.get("mdtv") else None))

    task_repo = TaskRepository(config.paths.target_root / ".mdcn2" / "tasks.db")
    return ScrapeOrchestrator(
        config=config,
        registry=CrawlerRegistry(crawlers),
        metadata_pipeline=MetadataPipeline(),
        resource_pipeline=ResourcePipeline(
            proxy=config.network.proxy,
            timeout=config.network.timeout,
            max_images=config.output.max_images,
        ),
        writer=OutputWriter(),
        organizer=FileOrganizer(),
        task_repo=task_repo,
    )
