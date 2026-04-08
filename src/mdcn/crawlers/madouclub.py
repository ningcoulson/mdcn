"""MadouClub crawler."""

from __future__ import annotations

import re
from urllib.parse import quote, urljoin

import httpx
from parsel import Selector

from mdcn.domain.errors import CrawlMismatchError, ParseError, SearchError
from mdcn.domain.models import ImageAsset, MetadataResult, NumberCandidate

from .base import BaseCrawler


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class MadouClubCrawler(BaseCrawler):
    @property
    def name(self) -> str:
        return "madouclub"

    @property
    def default_base_url(self) -> str:
        return "https://madou.club"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        queries = self._build_queries(candidate.normalized, file_hint)
        if not queries:
            raise SearchError("madouclub requires at least one search query")

        client = await self.ensure_client()
        for query in queries:
            try:
                response = await client.get(f"{self.base_url}/?s={quote(query)}")
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            if detail_url := self._parse_search_page(response.text, candidate.normalized):
                return detail_url
        raise SearchError(f"madouclub did not find a match for {candidate.normalized}")

    async def parse(
        self,
        html: str,
        url: str,
        candidate: NumberCandidate,
        *,
        file_hint: str = "",
    ) -> MetadataResult:
        selector = Selector(text=html)
        title = _clean_text(selector.css("h1.article-title::text").get(""))
        if not title:
            raise ParseError("madouclub detail page is missing a title")

        number = self._extract_number(title) or self._extract_number_from_url(url) or candidate.normalized
        if not self._matches_expected_number(candidate.normalized, number):
            raise CrawlMismatchError(f"madouclub matched unexpected number: {number}")

        tags = [_clean_text(tag) for tag in selector.css(".article-tags a::text").getall() if _clean_text(tag)]
        studio = _clean_text(selector.css("meta[property='og:site_name']::attr(content)").get("")) or "MadouClub"
        outline = "\n".join(
            text
            for text in (_clean_text(item) for item in selector.css(".article-content p::text, .article-content li::text").getall())
            if text
        )
        images = self._collect_images(selector, url)

        return MetadataResult(
            number=number,
            title=title.replace(number, "", 1).strip() if title.upper().startswith(number.upper()) else title,
            outline=outline,
            studio=studio,
            publisher=studio,
            tags=tags,
            images=images,
        )

    def _build_queries(self, number: str, file_hint: str) -> list[str]:
        values = [number, re.sub(r"[^0-9A-Za-z]", "", number), file_hint]
        if file_hint:
            values.extend(part for part in re.split(r"[\s._-]", file_hint) if len(part) >= 4)

        queries: list[str] = []
        seen: set[str] = set()
        for value in values:
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                queries.append(value)
        return queries

    def _parse_search_page(self, html: str, expected_number: str) -> str | None:
        selector = Selector(text=html)
        for node in selector.css("article.excerpt h2 a, .excerpt h2 a, .entry-title a"):
            href = node.attrib.get("href")
            title = _clean_text(node.css("::text").get("") or node.attrib.get("title", ""))
            if href and self._matches_expected_number(expected_number, title):
                return urljoin(self.base_url, href)
        return None

    def _collect_images(self, selector: Selector, detail_url: str) -> list[ImageAsset]:
        images: list[ImageAsset] = []
        urls: list[str] = []

        for script in selector.css("script::text").getall():
            if match := re.search(r"shareimage\s*:\s*'([^']+)'", script):
                urls.append(urljoin(detail_url, match.group(1)))

        for image in selector.css(".article-content img, .article img"):
            src = image.attrib.get("data-src") or image.attrib.get("data-original") or image.attrib.get("src") or ""
            if src:
                urls.append(urljoin(detail_url, src))

        seen: set[str] = set()
        for index, url in enumerate(urls, start=1):
            if url in seen:
                continue
            seen.add(url)
            images.append(ImageAsset(url=url, kind="poster" if index == 1 else "extrafanart"))
        return images

    def _extract_number(self, text: str) -> str:
        match = re.search(r"([A-Za-z]{2,}\d+(?:-\d+)?)", text.replace(" ", ""))
        return match.group(1).upper() if match else ""

    def _extract_number_from_url(self, url: str) -> str:
        match = re.search(r"/([a-z]+\d+(?:-\d+)?)(?:[-/]|$)", url, re.IGNORECASE)
        return match.group(1).upper() if match else ""

    def _matches_expected_number(self, expected: str, actual_text: str) -> bool:
        return bool(self._normalize_tokens(expected) & self._normalize_tokens(actual_text))

    def _normalize_tokens(self, value: str) -> set[str]:
        compact = re.sub(r"[^0-9A-Za-z]", "", value).upper()
        if not compact:
            return set()
        tokens = {compact}
        if match := re.match(r"([A-Z0-9]*?[A-Z][A-Z0-9]*?)(\d+)$", compact):
            tokens.add(f"{match.group(1)}{match.group(2).lstrip('0') or '0'}")
        return tokens
