"""AvJia crawler."""

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


class AvJiaCrawler(BaseCrawler):
    @property
    def name(self) -> str:
        return "avjia"

    @property
    def default_base_url(self) -> str:
        return "https://avjia.net"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        queries = self._build_queries(candidate.normalized, file_hint)
        if not queries:
            raise SearchError("avjia requires at least one search query")

        client = await self.ensure_client()
        for query in queries:
            try:
                response = await client.get(f"{self.base_url}/?s={quote(query)}", follow_redirects=True)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            if detail_url := self._parse_search_page(response.text, candidate.normalized):
                return detail_url
        raise SearchError(f"avjia did not find a match for {candidate.normalized}")

    async def parse(
        self,
        html: str,
        url: str,
        candidate: NumberCandidate,
        *,
        file_hint: str = "",
    ) -> MetadataResult:
        selector = Selector(text=html)
        title = self._extract_title(selector)
        if not title:
            raise ParseError("avjia detail page is missing a title")

        number = self._extract_number(title) or self._extract_number(url) or candidate.normalized
        if not self._matches_expected_number(candidate.normalized, number):
            raise CrawlMismatchError(f"avjia matched unexpected number: {number}")

        outline = self._extract_outline(selector)
        actors = self._extract_actor_list(selector)
        tags = self._extract_tag_list(selector)
        studio = self._extract_studio(selector)
        release_date, year = self._extract_release(selector)
        images = self._collect_images(selector, url)

        cleaned_title = title.replace(number, "", 1).strip(" -") if title.upper().startswith(number.upper()) else title
        return MetadataResult(
            number=number,
            title=cleaned_title or title,
            outline=outline,
            release_date=release_date,
            year=year,
            actors=actors,
            tags=tags,
            studio=studio,
            publisher=studio,
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
        for node in selector.css("article h2 a, .entry-title a, .post-title a, .video-item a"):
            href = node.attrib.get("href")
            title = _clean_text(node.css("::text").get("") or node.attrib.get("title", ""))
            if href and self._matches_expected_number(expected_number, title):
                return urljoin(self.base_url, href)
        return None

    def _extract_title(self, selector: Selector) -> str:
        for css in ("h1.entry-title::text", "h1.post-title::text", "h1::text", "title::text"):
            value = _clean_text(selector.css(css).get(""))
            if value and "404" not in value.lower() and "搜索结果" not in value:
                return value
        return ""

    def _extract_outline(self, selector: Selector) -> str:
        for css in (".entry-content p::text", ".post-content p::text", ".video-content p::text", ".desc::text"):
            values = [_clean_text(item) for item in selector.css(css).getall() if _clean_text(item)]
            if values:
                return "\n".join(values[:3])
        return ""

    def _extract_actor_list(self, selector: Selector) -> list[str]:
        patterns = (
            ".actors a::text",
            ".actor a::text",
            ".actor::text",
            ".performer a::text",
        )
        for css in patterns:
            actors = [_clean_text(item) for item in selector.css(css).getall() if _clean_text(item)]
            if actors:
                return actors
        return []

    def _extract_tag_list(self, selector: Selector) -> list[str]:
        for css in (".tags a::text", ".tag a::text", ".category a::text", ".genre a::text"):
            tags = [_clean_text(item) for item in selector.css(css).getall() if _clean_text(item)]
            if tags:
                return tags
        return []

    def _extract_studio(self, selector: Selector) -> str:
        for css in (".studio::text", ".maker::text", ".company::text", ".producer::text"):
            value = _clean_text(selector.css(css).get(""))
            if value:
                return value
        return "AvJia"

    def _extract_release(self, selector: Selector) -> tuple[datetime.date | None, int | None]:
        for css in (".date::text", ".release-date::text", "time::text", "time::attr(datetime)"):
            value = _clean_text(selector.css(css).get(""))
            if not value:
                continue
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
                try:
                    parsed = datetime.strptime(value, fmt).date()
                    return parsed, parsed.year
                except ValueError:
                    continue
        return None, None

    def _collect_images(self, selector: Selector, detail_url: str) -> list[ImageAsset]:
        images: list[ImageAsset] = []
        seen: set[str] = set()
        for image in selector.css(".poster img, .entry-content img, .gallery img, .post-content img, img"):
            src = image.attrib.get("data-src") or image.attrib.get("data-original") or image.attrib.get("src") or ""
            if not src:
                continue
            if not self._looks_like_media_image(src):
                continue
            full_url = urljoin(detail_url, src)
            if full_url in seen:
                continue
            seen.add(full_url)
            kind = "poster" if not images else "extrafanart"
            images.append(ImageAsset(url=full_url, kind=kind))
        return images

    def _looks_like_media_image(self, src: str) -> bool:
        lowered = src.lower()
        if any(token in lowered for token in ("logo", "avatar", "icon", "banner", "ad-")):
            return False
        return any(ext in lowered for ext in (".jpg", ".jpeg", ".png", ".webp")) or any(
            token in lowered for token in ("cover", "poster", "screen", "shot", "gallery")
        )

    def _extract_number(self, text: str) -> str:
        compact = re.sub(r"[^0-9A-Za-z]", "", text).upper()
        match = re.match(r"([A-Z0-9]*?[A-Z][A-Z0-9]*?)(\d{2,5})", compact)
        if not match:
            return ""
        return f"{match.group(1)}-{match.group(2).zfill(max(3, len(match.group(2))))}"

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
