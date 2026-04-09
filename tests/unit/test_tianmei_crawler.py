from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mdcn.crawlers.tianmei import TianmeiCrawler
from mdcn.domain.errors import CrawlMismatchError, SearchError
from mdcn.domain.models import NumberCandidate


@pytest.mark.asyncio
async def test_tianmei_parse_fixture_generates_result():
    html = (Path(__file__).parents[1] / "fixtures" / "tianmei_detail.html").read_text(encoding="utf-8")
    crawler = TianmeiCrawler()

    result = await crawler.parse(
        html,
        "https://www.94mt.cc/index.php/vod/detail/id/571.html",
        NumberCandidate(raw="91KCM010", normalized="91KCM010"),
    )

    assert result.number == "91KCM-010"
    assert result.title == "女高中生肉体还父债"
    assert result.studio == "91制片厂"
    assert result.actors == ["金宝娜"]
    assert "替父还债" in result.outline
    assert result.images[0].kind == "poster"
    assert result.images[0].url.endswith("4dd55c41a77226b862fa8e96807842e5.jpg")


@pytest.mark.asyncio
async def test_tianmei_search_and_run_with_mock_transport():
    search_html = (Path(__file__).parents[1] / "fixtures" / "tianmei_search.html").read_text(encoding="utf-8")
    detail_html = (Path(__file__).parents[1] / "fixtures" / "tianmei_detail.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "wd=91KCM010" in url:
            return httpx.Response(200, text=search_html)
        if url.endswith("/index.php/vod/detail/id/571.html"):
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = TianmeiCrawler(client=client)
        result = await crawler.run(NumberCandidate(raw="91KCM010", normalized="91KCM010"))

    assert result.number == "91KCM-010"
    assert result.website.endswith("/index.php/vod/detail/id/571.html")


@pytest.mark.asyncio
async def test_tianmei_parse_rejects_mismatch_detail():
    crawler = TianmeiCrawler()
    html = "<title>91制片厂・91KCM-999・其他影片详情介绍 - 天美影院</title>"

    with pytest.raises(CrawlMismatchError):
        await crawler.parse(
            html,
            "https://www.94mt.cc/index.php/vod/detail/id/999.html",
            NumberCandidate(raw="91KCM010", normalized="91KCM010"),
        )


@pytest.mark.asyncio
async def test_tianmei_search_raises_when_no_match():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html></html>"))) as client:
        crawler = TianmeiCrawler(client=client)
        with pytest.raises(SearchError):
            await crawler.run(NumberCandidate(raw="91KCM010", normalized="91KCM010"))
