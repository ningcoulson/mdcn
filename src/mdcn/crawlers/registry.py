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

    def get_enabled(
        self,
        site_configs: Mapping[str, SiteConfig] | None = None,
        site_order: tuple[str, ...] | list[str] | None = None,
    ) -> list[BaseCrawler]:
        if site_configs is None:
            enabled = self.get_all()
        else:
            enabled: list[BaseCrawler] = []
            for crawler in self._crawlers:
                site_config = site_configs.get(crawler.name)
                if site_config is None or site_config.enabled:
                    enabled.append(crawler)

        if not site_order:
            return enabled

        order_index = {name: index for index, name in enumerate(site_order)}
        enabled.sort(key=lambda crawler: (order_index.get(crawler.name, len(order_index)), self._crawlers.index(crawler)))
        return enabled
