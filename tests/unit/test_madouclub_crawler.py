from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mdcn.crawlers.madouclub import MadouClubCrawler
from mdcn.domain.errors import CrawlMismatchError, SearchError
from mdcn.domain.models import NumberCandidate


@pytest.mark.asyncio
async def test_madouclub_parse_fixture_generates_result():
    html = (Path(__file__).parents[1] / "fixtures" / "madouclub_detail.html").read_text(encoding="utf-8")
    crawler = MadouClubCrawler()

    result = await crawler.parse(
        html,
        "https://madou.club/mdwp0034-feature/",
        NumberCandidate(raw="MDWP0034", normalized="MDWP0034"),
    )

    assert result.number == "MDWP0034"
    assert result.title == "夜色密约"
    assert result.studio == "Madou Club"
    assert "夜色刚落" in result.outline
    assert result.images[0].kind == "poster"
    assert result.images[0].url.endswith("mdwp0034-share.jpg")
    assert result.images[1].kind == "extrafanart"


@pytest.mark.asyncio
async def test_madouclub_search_and_run_with_mock_transport():
    search_html = (Path(__file__).parents[1] / "fixtures" / "madouclub_search.html").read_text(encoding="utf-8")
    detail_html = (Path(__file__).parents[1] / "fixtures" / "madouclub_detail.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "?s=MDWP0034" in url:
            return httpx.Response(200, text=search_html)
        if url.endswith("/mdwp0034-feature/"):
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = MadouClubCrawler(client=client)
        result = await crawler.run(NumberCandidate(raw="MDWP0034", normalized="MDWP0034"))

    assert result.number == "MDWP0034"
    assert result.website.endswith("/mdwp0034-feature/")


@pytest.mark.asyncio
async def test_madouclub_parse_rejects_mismatch_detail():
    crawler = MadouClubCrawler()
    html = "<h1 class='article-title'>MDWP0099 其他影片</h1>"

    with pytest.raises(CrawlMismatchError):
        await crawler.parse(
            html,
            "https://madou.club/mdwp0099-other/",
            NumberCandidate(raw="MDWP0034", normalized="MDWP0034"),
        )


@pytest.mark.asyncio
async def test_madouclub_search_raises_when_no_match():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html></html>"))) as client:
        crawler = MadouClubCrawler(client=client)
        with pytest.raises(SearchError):
            await crawler.run(NumberCandidate(raw="MDWP0034", normalized="MDWP0034"))
