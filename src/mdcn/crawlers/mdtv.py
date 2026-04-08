"""MadouTV crawler."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

import httpx
from parsel import Selector

from mdcn.domain.errors import CrawlMismatchError, ParseError, SearchError
from mdcn.domain.models import ImageAsset, MetadataResult, NumberCandidate

from .base import BaseCrawler


def _strip(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _sanitize_number(raw: str) -> str:
    value = raw.strip().upper()
    if "-" not in value:
        match = re.match(r"([A-Z0-9]*?[A-Z][A-Z0-9]*?)(\d{2,5})$", value)
        if match:
            return f"{match.group(1)}-{match.group(2).zfill(max(3, len(match.group(2))))}"
    return value


class MadouTVCrawler(BaseCrawler):
    @property
    def name(self) -> str:
        return "mdtv"

    @property
    def default_base_url(self) -> str:
        return "https://www.mdpjzip.xyz"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        queries = self._build_queries(candidate.normalized, file_hint)
        if not queries:
            raise SearchError("mdtv requires at least one search query")

        client = await self.ensure_client()
        search_url = urljoin(self.base_url, "/index.php/vodsearch/-------------.html")
        for query in queries:
            try:
                response = await client.post(search_url, data={"wd": query})
            except httpx.HTTPError:
                continue
            if response.status_code != 200:
                continue
            selector = Selector(text=response.text)
            for node in selector.css("h4.post-title a"):
                title = _strip(node.attrib.get("title", ""))
                href = node.attrib.get("href", "")
                if href and self._matches_expected_number(candidate.normalized, title):
                    return urljoin(self.base_url, href)
        raise SearchError(f"mdtv did not find a match for {candidate.normalized}")

    async def parse(
        self,
        html: str,
        url: str,
        candidate: NumberCandidate,
        *,
        file_hint: str = "",
    ) -> MetadataResult:
        selector = Selector(text=html)
        title_raw = _strip(selector.css("div.blog-single div a::attr(title)").get(""))
        if not title_raw:
            raise ParseError("mdtv detail page is missing a title")

        number = candidate.normalized
        inferred_number = self._extract_number(title_raw)
        if inferred_number:
            number = inferred_number
        if not self._matches_expected_number(candidate.normalized, number):
            raise CrawlMismatchError(f"mdtv matched unexpected number: {number}")

        cover = selector.css("div.blog-single div a img::attr(src)").get("")
        cover = urljoin(url, cover) if cover else ""

        series = _strip(selector.xpath("(//div[@class='category'])[1]/text()").get(""))
        tags = [_strip(item) for item in selector.xpath("(//div[@class='category'])[2]/a/text()").getall() if _strip(item)]
        actors = [
            _strip(item)
            for item in selector.xpath("(//div[@class='category'])[3]/a/text()").getall()
            if _strip(item) and "未知" not in item
        ]

        if not actors:
            actors = list(dict.fromkeys(re.findall(r"[\u4e00-\u9fa5]{2,3}", title_raw)))

        title = title_raw.replace(number, "").strip() if number in title_raw else title_raw
        release_date, year = self._extract_release(cover, selector)
        outline = "\n".join(_strip(p) for p in selector.css("div.details-content p::text").getall() if _strip(p))
        images = self._collect_images(url, cover, selector)

        return MetadataResult(
            number=number,
            title=title or title_raw,
            outline=outline,
            release_date=release_date,
            year=year,
            actors=actors,
            tags=tags,
            studio=series,
            publisher=series,
            series=series,
            images=images,
        )

    def _build_queries(self, number: str, file_hint: str) -> list[str]:
        values = [number, number.replace("-", ""), file_hint]
        if file_hint:
            values.extend(part for part in re.split(r"[\s.\-]", file_hint) if len(part) >= 3)
        queries: list[str] = []
        seen: set[str] = set()
        for value in values:
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                queries.append(value)
        return queries

    def _extract_number(self, title_raw: str) -> str:
        compact = re.sub(r"[^0-9A-Za-z]", "", title_raw).upper()
        match = re.match(r"([A-Z0-9]*?[A-Z][A-Z0-9]*?)(\d{2,5})", compact)
        if not match:
            return ""
        return f"{match.group(1)}-{match.group(2).zfill(max(3, len(match.group(2))))}"

    def _matches_expected_number(self, expected: str, actual_text: str) -> bool:
        expected_tokens = self._normalize_tokens(expected)
        actual_tokens = self._normalize_tokens(actual_text)
        return bool(expected_tokens & actual_tokens)

    def _normalize_tokens(self, value: str) -> set[str]:
        tokens: set[str] = set()
        compact = re.sub(r"[^0-9A-Za-z]", "", value).upper()
        if not compact:
            return tokens
        tokens.add(compact)
        if match := re.match(r"([A-Z0-9]*?[A-Z][A-Z0-9]*?)(\d+)$", compact):
            tokens.add(f"{match.group(1)}{match.group(2).lstrip('0') or '0'}")
        return tokens

    def _extract_release(self, cover: str, selector: Selector) -> tuple[datetime.date | None, int | None]:
        release_date = None
        year = None
        text = _strip(selector.css("span.date::text").get(""))
        if text:
            try:
                dt = datetime.strptime(text, "%Y-%m-%d")
                release_date = dt.date()
                year = dt.year
            except ValueError:
                pass
        if not release_date and cover:
            if match := re.search(r"/(\d{4})(\d{2})(\d{2})-", cover):
                dt = datetime.strptime("".join(match.groups()), "%Y%m%d")
                release_date = dt.date()
                year = dt.year
        return release_date, year

    def _collect_images(self, detail_url: str, cover: str, selector: Selector) -> list[ImageAsset]:
        images: list[ImageAsset] = []
        if cover:
            images.append(ImageAsset(url=re.sub(r"-\d+x\d+(?=\.[a-zA-Z]+$)", "", cover), kind="poster"))
        for node in selector.css("div.content img"):
            src = node.attrib.get("data-original") or node.attrib.get("src") or ""
            if not src:
                continue
            full = urljoin(detail_url, src)
            images.append(ImageAsset(url=re.sub(r"-\d+x\d+(?=\.[a-zA-Z]+$)", "", full), kind="extrafanart"))
        return images
