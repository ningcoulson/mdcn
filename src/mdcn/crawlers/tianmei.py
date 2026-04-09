"""Tianmei crawler."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote, urljoin

import httpx
from parsel import Selector

from mdcn.domain.errors import CrawlMismatchError, ParseError, SearchError
from mdcn.domain.models import ImageAsset, MetadataResult, NumberCandidate

from .base import BaseCrawler


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class TianmeiCrawler(BaseCrawler):
    @property
    def name(self) -> str:
        return "tianmei"

    @property
    def default_base_url(self) -> str:
        return "https://www.94mt.cc"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        queries = self._build_queries(candidate.normalized, file_hint)
        if not queries:
            raise SearchError("tianmei requires at least one search query")

        client = await self.ensure_client()
        for query in queries:
            url = f"{self.base_url}/index.php/vod/search.html?wd={quote(query)}"
            try:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            if detail_url := self._parse_search_page(response.text, candidate.normalized):
                return detail_url
        raise SearchError(f"tianmei did not find a match for {candidate.normalized}")

    async def parse(
        self,
        html: str,
        url: str,
        candidate: NumberCandidate,
        *,
        file_hint: str = "",
    ) -> MetadataResult:
        selector = Selector(text=html)
        raw_title = self._extract_raw_title(selector)
        if not raw_title:
            raise ParseError("tianmei detail page is missing a title")

        studio, number, actors, title = self._split_title(raw_title, candidate.normalized)
        if not self._matches_expected_number(candidate.normalized, number):
            raise CrawlMismatchError(f"tianmei matched unexpected number: {number}")

        outline = self._extract_outline(selector)
        release_date, year = self._extract_release(selector)
        tags = self._extract_tags(selector, studio)
        images = self._collect_images(selector, url)

        return MetadataResult(
            number=number,
            title=title,
            outline=outline,
            actors=actors,
            tags=tags,
            studio=studio,
            publisher=studio,
            release_date=release_date,
            year=year,
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
        for card in selector.css(".box-item"):
            href = card.css("a.item-link::attr(href)").get("") or card.css("a.movie-name::attr(href)").get("")
            title = _clean_text(card.css("a.item-link::attr(title)").get("")) or _clean_text(
                card.css("a.movie-name::text").get("")
            ) or _clean_text(card.css("a.movie-name::attr(title)").get(""))
            if href and title and self._matches_expected_number(expected_number, title):
                return urljoin(self.base_url, href)
        return None

    def _extract_raw_title(self, selector: Selector) -> str:
        title = _clean_text(selector.css("title::text").get(""))
        if title:
            title = re.sub(r"(详情介绍|在线点播迅雷下载)\s*-\s*天美影院$", "", title)
            return title.strip(" -")
        return ""

    def _split_title(self, raw_title: str, fallback_number: str) -> tuple[str, str, list[str], str]:
        parts = [_clean_text(part) for part in raw_title.split("・") if _clean_text(part)]
        if not parts:
            return "", fallback_number, [], raw_title

        studio = parts[0] if len(parts) >= 2 else ""
        number = fallback_number
        title = raw_title
        actors: list[str] = []

        number_index = -1
        for index, part in enumerate(parts):
            extracted = self._extract_number(part)
            if extracted:
                number = extracted
                number_index = index
                break

        if number_index >= 0:
            tail = parts[number_index + 1 :]
            if tail:
                if len(tail) >= 2:
                    actors = [item for item in tail[:-1] if self._looks_like_actor(item)]
                    title = tail[-1]
                else:
                    title = tail[0]
            else:
                title = raw_title

        title = _clean_text(title)
        if title == raw_title:
            title = self._strip_prefix(raw_title, studio, number)
        return studio, number, actors, title or raw_title

    def _strip_prefix(self, raw_title: str, studio: str, number: str) -> str:
        value = raw_title
        for token in (studio, number):
            if token:
                value = re.sub(rf"^{re.escape(token)}[・\s-]*", "", value)
        return value.strip(" ・-_")

    def _looks_like_actor(self, value: str) -> bool:
        return bool(value) and len(value) <= 12 and not self._extract_number(value)

    def _extract_outline(self, selector: Selector) -> str:
        summary = _clean_text(selector.css("p.summary::text").get(""))
        if summary and summary != "…":
            return summary
        return ""

    def _extract_release(self, selector: Selector) -> tuple[datetime.date | None, int | None]:
        texts = selector.css(".ptime em::text, .con-detail .li_r::text").getall()
        for text in texts:
            cleaned = _clean_text(text)
            match = re.search(r"(\d{4}-\d{2}-\d{2})", cleaned)
            if not match:
                continue
            parsed = datetime.strptime(match.group(1), "%Y-%m-%d").date()
            return parsed, parsed.year
        return None, None

    def _extract_tags(self, selector: Selector, studio: str) -> list[str]:
        tags = [_clean_text(item) for item in selector.css(".con-detail a::text").getall() if _clean_text(item)]
        if studio and studio not in tags:
            tags.insert(0, studio)
        return tags

    def _collect_images(self, selector: Selector, detail_url: str) -> list[ImageAsset]:
        images: list[ImageAsset] = []
        src = selector.css(".img-thumbnail::attr(src), .con-pic img::attr(src)").get("")
        if src:
            images.append(ImageAsset(url=urljoin(detail_url, src), kind="poster"))
        return images

    def _extract_number(self, value: str) -> str:
        compact = re.sub(r"[^0-9A-Za-z]", "", value).upper()
        match = re.search(r"([A-Z0-9]*?[A-Z][A-Z0-9]*?)(\d{2,5})", compact)
        if not match:
            return ""
        prefix, digits = match.groups()
        return f"{prefix}-{digits.zfill(max(3, len(digits)))}"

    def _matches_expected_number(self, expected: str, actual_text: str) -> bool:
        return bool(self._normalize_tokens(expected) & self._normalize_tokens(actual_text))

    def _normalize_tokens(self, value: str) -> set[str]:
        tokens: set[str] = set()
        for part in [part.upper() for part in re.split(r"[^0-9A-Za-z]+", value) if part]:
            tokens.add(part)
        compact = re.sub(r"[^0-9A-Za-z]", "", value).upper()
        if compact:
            tokens.add(compact)
        raw_value = value.upper()
        for part in [raw_value, *list(tokens)]:
            for match in re.finditer(r"([A-Z0-9]*?[A-Z][A-Z0-9]*?)[^0-9A-Z]{0,3}(\d{2,5})", part):
                prefix, digits = match.groups()
                tokens.add(f"{prefix}{digits}")
                tokens.add(f"{prefix}{digits.lstrip('0') or '0'}")
                tokens.add(f"{prefix}-{digits.zfill(max(3, len(digits)))}")
        return tokens
