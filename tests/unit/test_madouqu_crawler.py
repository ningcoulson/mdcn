from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mdcn2.crawlers.madouqu import MadouQuCrawler
from mdcn2.domain.errors import CrawlMismatchError, SearchError
from mdcn2.domain.models import NumberCandidate


@pytest.mark.asyncio
async def test_madouqu_parse_fixture_generates_result():
    html = (Path(__file__).parents[1] / "fixtures" / "madouqu_detail.html").read_text(encoding="utf-8")
    crawler = MadouQuCrawler()

    result = await crawler.parse(
        html,
        "https://madouqu.cc/archives/md-0001",
        NumberCandidate(raw="MD-0001", normalized="MD-0001"),
    )

    assert result.number == "MD-0001"
    assert result.title == "激情序幕"
    assert result.year == 2024
    assert result.release_date.isoformat() == "2024-08-15"
    assert "令人心动" in result.outline
    assert {"林可菲", "苏语堂"}.issubset(result.actors)
    assert result.images[0].kind == "poster"
    assert result.images[0].url.endswith("md-0001-cover.jpg")
    assert result.images[1].kind == "extrafanart"
    assert result.images[1].url.endswith("md-0001-shot1.jpg")


@pytest.mark.asyncio
async def test_madouqu_run_with_mock_transport_searches_and_parses():
    search_html = (Path(__file__).parents[1] / "fixtures" / "madouqu_search.html").read_text(encoding="utf-8")
    detail_html = (Path(__file__).parents[1] / "fixtures" / "madouqu_detail.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "?s=MD-0001" in url:
            return httpx.Response(200, text=search_html)
        if url.endswith("/archives/md-0001"):
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        crawler = MadouQuCrawler(client=client)
        result = await crawler.run(NumberCandidate(raw="MD-0001", normalized="MD-0001"))

    assert result.number == "MD-0001"
    assert result.website.endswith("/archives/md-0001")
    assert result.source == "madouqu"


@pytest.mark.asyncio
async def test_madouqu_search_rejects_partial_match():
    search_html = """
    <div class="entry-media">
      <div>
        <a href="/video/md0010/"><img src="thumb.jpg" alt="MD0010 其他影片"></a>
      </div>
    </div>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if "?s=MD-0001" in str(request.url):
            return httpx.Response(200, text=search_html)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        crawler = MadouQuCrawler(client=client)
        with pytest.raises(SearchError):
            await crawler.run(NumberCandidate(raw="MD-0001", normalized="MD-0001"))


@pytest.mark.asyncio
async def test_madouqu_parse_rejects_mismatch_detail():
    html = """
    <div class="cao_entry_header"><header><h1>MD-0010 其他影片</h1></header></div>
    <div class="entry-content u-text-format u-clearfix">
      <p>番号：MD-0010</p>
    </div>
    """
    crawler = MadouQuCrawler()

    with pytest.raises(CrawlMismatchError):
        await crawler.parse(
            html,
            "https://madouqu.cc/archives/md-0010",
            NumberCandidate(raw="MD-0001", normalized="MD-0001"),
        )
