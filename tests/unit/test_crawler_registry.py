from __future__ import annotations

from mdcn.config.models import SiteConfig
from mdcn.crawlers.base import BaseCrawler
from mdcn.crawlers.registry import CrawlerRegistry
from mdcn.domain.models import MetadataResult, NumberCandidate


class FakeCrawler(BaseCrawler):
    def __init__(self, crawler_name: str) -> None:
        self._crawler_name = crawler_name
        super().__init__(base_url="https://example.com")

    @property
    def name(self) -> str:
        return self._crawler_name

    @property
    def default_base_url(self) -> str:
        return "https://example.com"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        return self.base_url

    async def parse(
        self,
        html: str,
        url: str,
        candidate: NumberCandidate,
        *,
        file_hint: str = "",
    ) -> MetadataResult:
        return MetadataResult(number=candidate.normalized, title="ok")


def test_registry_returns_all_crawlers():
    registry = CrawlerRegistry([FakeCrawler("madouqu"), FakeCrawler("mdtv")])
    assert [crawler.name for crawler in registry.get_all()] == ["madouqu", "mdtv"]


def test_registry_filters_disabled_sites():
    registry = CrawlerRegistry([FakeCrawler("madouqu"), FakeCrawler("mdtv"), FakeCrawler("avjia")])

    enabled = registry.get_enabled(
        {
            "madouqu": SiteConfig(enabled=True, base_url="https://a"),
            "mdtv": SiteConfig(enabled=False, base_url="https://b"),
        }
    )

    assert [crawler.name for crawler in enabled] == ["madouqu", "avjia"]
