from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mdcn.crawlers.mdtv import MadouTVCrawler
from mdcn.domain.errors import SearchError
from mdcn.domain.models import NumberCandidate


@pytest.mark.asyncio
async def test_mdtv_parse_from_fixture():
    html = (Path(__file__).parents[1] / "fixtures" / "mdtv_detail.html").read_text(encoding="utf-8")
    crawler = MadouTVCrawler()

    result = await crawler.parse(
        html,
        "https://www.mdpjzip.xyz/detail/123",
        NumberCandidate(raw="MDTV123", normalized="MDTV123"),
    )

    assert result.number == "MDTV-123"
    assert result.title == "激情再现"
    assert result.year == 2024
    assert result.release_date.isoformat() == "2024-01-18"
    assert set(result.tags) == {"原创剧情", "都市"}
    assert set(result.actors) == {"林可菲", "苏语堂"}
    assert result.series == "麻豆传媒映画"
    assert result.images[0].kind == "poster"
    assert result.images[0].url.endswith("mdtv-123-cover.jpg")
    assert result.images[1].kind == "extrafanart"


@pytest.mark.asyncio
async def test_mdtv_search_and_run_with_mock_transport():
    search_html = """
    <h4 class="post-title"><a title="MDTV-123 激情再现" href="/detail/123">MDTV-123 激情再现</a></h4>
    """
    detail_html = (Path(__file__).parents[1] / "fixtures" / "mdtv_detail.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url).endswith("/index.php/vodsearch/-------------.html"):
            return httpx.Response(200, text=search_html)
        if str(request.url).endswith("/detail/123"):
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = MadouTVCrawler(client=client)
        result = await crawler.run(NumberCandidate(raw="MDTV123", normalized="MDTV123"))

    assert result.number == "MDTV-123"
    assert result.website.endswith("/detail/123")


@pytest.mark.asyncio
async def test_mdtv_search_raises_when_no_match():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html></html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = MadouTVCrawler(client=client)
        with pytest.raises(SearchError):
            await crawler.run(NumberCandidate(raw="MDTV123", normalized="MDTV123"))
