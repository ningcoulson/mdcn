"""Runtime wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mdcn.config.models import AppConfig
from mdcn.crawlers import AvJiaCrawler, CrawlerRegistry, MadouClubCrawler, MadouQuCrawler, TianmeiCrawler
from mdcn.crawlers.mdtv import MadouTVCrawler
from mdcn.pipeline import FileOrganizer, MetadataPipeline, OutputWriter
from mdcn.pipeline.orchestrator import ScrapeOrchestrator
from mdcn.pipeline.resources import ResourcePipeline
from mdcn.storage.task_repo import TaskRepository


def build_crawlers(config: AppConfig) -> list[object]:
    crawlers = []
    if config.sites.get("madouqu", None) is None or config.sites["madouqu"].enabled:
        site = config.sites.get("madouqu")
        crawlers.append(
            MadouQuCrawler(
                base_url=site.base_url if site else None,
                mirrors=site.mirrors if site else (),
                proxy=config.network.proxy,
                timeout=config.network.timeout,
                retries=config.network.retries,
            )
        )
    if config.sites.get("mdtv", None) is None or config.sites["mdtv"].enabled:
        site = config.sites.get("mdtv")
        crawlers.append(
            MadouTVCrawler(
                base_url=site.base_url if site else None,
                mirrors=site.mirrors if site else (),
                proxy=config.network.proxy,
                timeout=config.network.timeout,
                retries=config.network.retries,
            )
        )
    if config.sites.get("madouclub", None) is None or config.sites["madouclub"].enabled:
        site = config.sites.get("madouclub")
        crawlers.append(
            MadouClubCrawler(
                base_url=site.base_url if site else None,
                mirrors=site.mirrors if site else (),
                proxy=config.network.proxy,
                timeout=config.network.timeout,
                retries=config.network.retries,
            )
        )
    if config.sites.get("avjia", None) is None or config.sites["avjia"].enabled:
        site = config.sites.get("avjia")
        crawlers.append(
            AvJiaCrawler(
                base_url=site.base_url if site else None,
                mirrors=site.mirrors if site else (),
                proxy=config.network.proxy,
                timeout=config.network.timeout,
                retries=config.network.retries,
            )
        )
    if config.sites.get("tianmei", None) is None or config.sites["tianmei"].enabled:
        site = config.sites.get("tianmei")
        crawlers.append(
            TianmeiCrawler(
                base_url=site.base_url if site else None,
                mirrors=site.mirrors if site else (),
                proxy=config.network.proxy,
                timeout=config.network.timeout,
                retries=config.network.retries,
            )
        )
    return crawlers


def build_orchestrator(
    config: AppConfig,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> ScrapeOrchestrator:
    task_repo = TaskRepository(config.paths.target_root / ".mdcn" / "tasks.db")
    return ScrapeOrchestrator(
        config=config,
        registry=CrawlerRegistry(build_crawlers(config)),
        metadata_pipeline=MetadataPipeline(),
        resource_pipeline=ResourcePipeline(
            proxy=config.network.proxy,
            timeout=config.network.timeout,
            retries=config.network.retries,
            max_images=config.output.max_images,
        ),
        writer=OutputWriter(),
        organizer=FileOrganizer(folder_template=config.output.folder_template),
        task_repo=task_repo,
        progress_callback=progress_callback,
    )
