"""Crawler registry."""

from __future__ import annotations

from collections.abc import Mapping

from mdcn.config.models import SiteConfig

from .base import BaseCrawler


class CrawlerRegistry:
    def __init__(self, crawlers: list[BaseCrawler]) -> None:
        self._crawlers = crawlers

    def get_all(self) -> list[BaseCrawler]:
        return list(self._crawlers)

    def get_enabled(self, site_configs: Mapping[str, SiteConfig] | None = None) -> list[BaseCrawler]:
        if site_configs is None:
            return self.get_all()

        enabled: list[BaseCrawler] = []
        for crawler in self._crawlers:
            site_config = site_configs.get(crawler.name)
            if site_config is None or site_config.enabled:
                enabled.append(crawler)
        return enabled
