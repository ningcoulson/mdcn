from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mdcn.crawlers.avjia import AvJiaCrawler
from mdcn.domain.errors import CrawlMismatchError, SearchError
from mdcn.domain.models import NumberCandidate


@pytest.mark.asyncio
async def test_avjia_parse_fixture_generates_result():
    html = (Path(__file__).parents[1] / "fixtures" / "avjia_detail.html").read_text(encoding="utf-8")
    crawler = AvJiaCrawler()

    result = await crawler.parse(
        html,
        "https://avjia.net/video/91cm017/",
        NumberCandidate(raw="91CM017", normalized="91CM017"),
    )

    assert result.number == "91CM-017"
    assert result.title == "东京街头搭讪女友计划"
    assert result.year == 2024
    assert result.release_date.isoformat() == "2024-02-14"
    assert set(result.actors) == {"苏曼妮", "夏晴"}
    assert set(result.tags) == {"剧情", "搭讪"}
    assert result.images[0].kind == "poster"
    assert result.images[1].kind == "extrafanart"


@pytest.mark.asyncio
async def test_avjia_search_and_run_with_mock_transport():
    search_html = (Path(__file__).parents[1] / "fixtures" / "avjia_search.html").read_text(encoding="utf-8")
    detail_html = (Path(__file__).parents[1] / "fixtures" / "avjia_detail.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "?s=91CM017" in url:
            return httpx.Response(200, text=search_html)
        if url.endswith("/video/91cm017/"):
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        crawler = AvJiaCrawler(client=client)
        result = await crawler.run(NumberCandidate(raw="91CM017", normalized="91CM017"))

    assert result.number == "91CM-017"
    assert result.website.endswith("/video/91cm017/")


@pytest.mark.asyncio
async def test_avjia_parse_rejects_mismatch_detail():
    crawler = AvJiaCrawler()
    html = "<h1 class='entry-title'>91CM-099 其他影片</h1>"

    with pytest.raises(CrawlMismatchError):
        await crawler.parse(
            html,
            "https://avjia.net/video/91cm099/",
            NumberCandidate(raw="91CM017", normalized="91CM017"),
        )


@pytest.mark.asyncio
async def test_avjia_search_raises_when_no_match():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="<html></html>"))) as client:
        crawler = AvJiaCrawler(client=client)
        with pytest.raises(SearchError):
            await crawler.run(NumberCandidate(raw="91CM017", normalized="91CM017"))


def test_avjia_matcher_recognizes_number_inside_longer_title():
    crawler = AvJiaCrawler()

    assert crawler._matches_expected_number("91KCM-045", "国足雄起之鸡不可失 -RONA 91KCM045")
    assert crawler._matches_expected_number("91KCM045", "91KCM045 国足雄起之鸡不可失 RONA")


def test_avjia_build_queries_filters_noisy_file_hint():
    crawler = AvJiaCrawler()
    queries = crawler._build_queries("XK-8193", "[ThZu.Cc]星空传媒XK8193儿媳大战-香菱.mp4")

    assert queries[0] == "XK-8193"
    assert "XK8193" in queries
    assert len(queries) <= 4
    assert all("[" not in query for query in queries)
