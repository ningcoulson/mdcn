from __future__ import annotations

from mdcn.config.models import SiteConfig
from mdcn.crawlers.base import BaseCrawler
from mdcn.crawlers.registry import CrawlerRegistry
from mdcn.domain.models import MetadataResult, NumberCandidate


class StubCrawler(BaseCrawler):
    def __init__(self, crawler_name: str) -> None:
        self._name = crawler_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def default_base_url(self) -> str:
        return "https://example.com"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        return "https://example.com/detail"

    async def fetch(self, url: str) -> str:
        return "<html></html>"

    async def parse(self, html: str, url: str, candidate: NumberCandidate, *, file_hint: str = "") -> MetadataResult:
        return MetadataResult(number=candidate.normalized, title="stub")


def test_registry_respects_site_order():
    registry = CrawlerRegistry([StubCrawler("madouqu"), StubCrawler("mdtv")])

    crawlers = registry.get_enabled(
        {"madouqu": SiteConfig(enabled=True), "mdtv": SiteConfig(enabled=True)},
        ("mdtv", "madouqu"),
    )

    assert [crawler.name for crawler in crawlers] == ["mdtv", "madouqu"]
