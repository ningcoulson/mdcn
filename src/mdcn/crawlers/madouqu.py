"""MadouQu crawler."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx
from parsel import Selector

from mdcn.domain.errors import CrawlMismatchError, ParseError, SearchError
from mdcn.domain.models import ImageAsset, MetadataResult, NumberCandidate

from .base import BaseCrawler


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_query(text: str) -> str:
    value = text.strip().replace("_", "-")
    value = re.sub(r"[^0-9A-Za-z\-]+", " ", value)
    return value.strip()


class MadouQuCrawler(BaseCrawler):
    @property
    def name(self) -> str:
        return "madouqu"

    @property
    def default_base_url(self) -> str:
        return "https://madouqu.cc"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        queries = self._build_queries(candidate.normalized, file_hint)
        if not queries:
            raise SearchError("madouqu requires at least one search query")

        client = await self.ensure_client()
        for query in queries:
            url = f"{self.base_url}/?s={quote(query)}"
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            if detail_url := self._parse_search_page(response.text, candidate.normalized):
                return detail_url
        raise SearchError(f"madouqu did not find a match for {candidate.normalized}")

    async def parse(
        self,
        html: str,
        url: str,
        candidate: NumberCandidate,
        *,
        file_hint: str = "",
    ) -> MetadataResult:
        selector = Selector(text=html)
        title_raw = _clean_text(selector.css("div.cao_entry_header header h1::text").get(""))
        if not title_raw:
            raise ParseError("madouqu detail page is missing a title")

        detail_texts = [
            _clean_text(text)
            for text in selector.xpath('//div[@class="entry-content u-text-format u-clearfix"]//text()').getall()
            if _clean_text(text)
        ]

        number = candidate.normalized
        title = title_raw
        actors: list[str] = []
        for text in detail_texts:
            if re.search(r"番号|番號", text):
                if match := re.search(r"(?:番号|番號)\s*[：:]?\s*(.+)", text):
                    number = _clean_text(match.group(1)).upper()
            if re.search(r"片名", text):
                if match := re.search(r"片名\s*[：:]\s*(.+)", text):
                    title = _clean_text(match.group(1))
            if re.search(r"女郎|演员|主演|主角|麻豆", text):
                if match := re.search(r"(?:女优女郎|麻豆女郎|麻豆|女郎|演员|主演|主角)[：:]\s*(.+)", text):
                    actors = [item.strip() for item in re.split(r"[、,，]", match.group(1)) if item.strip()]

        if not self._matches_expected_number(candidate.normalized, number):
            raise CrawlMismatchError(f"madouqu matched unexpected number: {number}")

        release_date = None
        year = None
        if time_str := selector.css("time::attr(datetime)").get():
            try:
                dt = datetime.fromisoformat(time_str)
            except ValueError:
                dt = None
            if dt is not None:
                release_date = dt.date()
                year = dt.year

        studio = _clean_text(selector.css("span.meta-category::text").get(""))
        outline = self._build_outline(detail_texts)
        images = self._collect_images(selector, url)

        return MetadataResult(
            number=number,
            title=title,
            outline=outline,
            actors=actors,
            studio=studio,
            publisher=studio,
            release_date=release_date,
            year=year,
            images=images,
        )

    def _build_queries(self, number: str, file_hint: str) -> list[str]:
        values = [number, _normalize_query(number), file_hint]
        if file_hint:
            values.extend(part for part in re.split(r"[\s.\-]", file_hint) if len(part) >= 4)

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
        for card in selector.css("div.entry-media > div > a"):
            href = card.attrib.get("href")
            title = _clean_text(card.css("img::attr(alt)").get(""))
            if href and self._matches_expected_number(expected_number, title):
                return urljoin(self.base_url, href)
        return None

    def _matches_expected_number(self, expected_number: str, actual_text: str) -> bool:
        expected_tokens = self._normalize_tokens(expected_number)
        actual_tokens = self._normalize_tokens(actual_text)
        return bool(expected_tokens & actual_tokens)

    def _normalize_tokens(self, value: str) -> set[str]:
        tokens: set[str] = set()
        base = re.sub(r"[^0-9A-Za-z]", "", value).upper()
        if not base:
            return tokens
        tokens.add(base)
        if match := re.match(r"([A-Z0-9]*?[A-Z][A-Z0-9]*?)(\d+)$", base):
            prefix, digits = match.groups()
            tokens.add(f"{prefix}{digits.lstrip('0') or '0'}")
        return tokens

    def _build_outline(self, detail_texts: list[str]) -> str:
        items = [
            text
            for text in detail_texts
            if not re.search(r"番[号號]|片名|女优|演员|女郎", text)
            and len(text) > 8
        ]
        return "\n".join(items[:3])

    def _collect_images(self, selector: Selector, detail_url: str) -> list[ImageAsset]:
        images: list[ImageAsset] = []
        for index, image in enumerate(selector.css("div.entry-content img"), start=1):
            src = image.attrib.get("data-src") or image.attrib.get("data-original") or image.attrib.get("src") or ""
            if not src:
                continue
            full_url = urljoin(detail_url, src)
            cleaned = self._normalize_image_url(full_url)
            kind = "poster" if index == 1 else "extrafanart"
            images.append(ImageAsset(url=cleaned, kind=kind))
        return images

    def _normalize_image_url(self, url: str) -> str:
        scheme, netloc, path, query, fragment = urlsplit(url)
        path = re.sub(r"-\d+x\d+(?=\.[a-zA-Z]+$)", "", path)
        return urlunsplit((scheme, netloc, path, "", ""))
