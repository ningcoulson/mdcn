from __future__ import annotations

import httpx
import pytest

from mdcn.crawlers.base import BaseCrawler
from mdcn.domain.errors import NetworkError, ParseError
from mdcn.domain.models import MetadataResult, NumberCandidate


class DummyCrawler(BaseCrawler):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def default_base_url(self) -> str:
        return "https://example.com"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        return f"{self.base_url}/detail/{candidate.normalized.lower()}"

    async def parse(
        self,
        html: str,
        url: str,
        candidate: NumberCandidate,
        *,
        file_hint: str = "",
    ) -> MetadataResult:
        return MetadataResult(number=candidate.normalized, title=html)


class EmptyNumberCrawler(DummyCrawler):
    async def parse(
        self,
        html: str,
        url: str,
        candidate: NumberCandidate,
        *,
        file_hint: str = "",
    ) -> MetadataResult:
        return MetadataResult(number="", title=html)


class FlakyCrawler(DummyCrawler):
    pass


@pytest.mark.asyncio
async def test_base_crawler_run_sets_source_and_website():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Parsed Title")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = DummyCrawler(client=client)
        result = await crawler.run(NumberCandidate(raw="MD-1", normalized="MD-001"))

    assert result.number == "MD-001"
    assert result.title == "Parsed Title"
    assert result.source == "dummy"
    assert result.website.endswith("/detail/md-001")


@pytest.mark.asyncio
async def test_base_crawler_wraps_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = DummyCrawler(client=client)
        with pytest.raises(NetworkError):
            await crawler.run(NumberCandidate(raw="MD-1", normalized="MD-001"))


@pytest.mark.asyncio
async def test_base_crawler_rejects_empty_number():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Parsed Title")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = EmptyNumberCrawler(client=client)
        with pytest.raises(ParseError):
            await crawler.run(NumberCandidate(raw="MD-1", normalized="MD-001"))


@pytest.mark.asyncio
async def test_base_crawler_resolves_to_healthy_mirror():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://bad.example.com/"):
            return httpx.Response(503, text="down")
        if url == "https://good.example.com/":
            return httpx.Response(200, text="ok")
        if url.endswith("/detail/md-001"):
            return httpx.Response(200, text="Parsed Title")
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = DummyCrawler(
            base_url="https://bad.example.com",
            mirrors=("https://good.example.com",),
            client=client,
        )
        result = await crawler.run(NumberCandidate(raw="MD-1", normalized="MD-001"))

    assert crawler.base_url == "https://good.example.com"
    assert result.website == "https://good.example.com/detail/md-001"


@pytest.mark.asyncio
async def test_base_crawler_retries_fetch_before_failing():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(502, text="boom")
        return httpx.Response(200, text="Recovered Title")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = DummyCrawler(client=client, retries=2)
        result = await crawler.run(NumberCandidate(raw="MD-1", normalized="MD-001"))

    assert attempts["count"] == 3
    assert result.title == "Recovered Title"
