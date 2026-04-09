"""AvJia crawler."""

from __future__ import annotations

import time
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
        return "https://1024kan.com"

    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        queries = self._build_queries(candidate.normalized, file_hint)
        if not queries:
            raise SearchError("avjia requires at least one search query")

        client = await self.ensure_client()
        search_budget_seconds = max(10.0, min(18.0, self.timeout + 2.0))
        started = time.monotonic()
        for query in queries:
            elapsed = time.monotonic() - started
            remaining_for_search = search_budget_seconds - elapsed
            if remaining_for_search <= 0:
                break
            for request_path, request_params in self._build_search_requests(query):
                elapsed = time.monotonic() - started
                remaining_for_search = search_budget_seconds - elapsed
                if remaining_for_search <= 0:
                    break
                request_timeout = max(2.5, min(self.timeout, remaining_for_search))
                try:
                    response = await client.get(
                        urljoin(self.base_url.rstrip("/") + "/", request_path.lstrip("/")),
                        params=request_params,
                        timeout=request_timeout,
                        follow_redirects=True,
                    )
                    response.raise_for_status()
                except httpx.HTTPError:
                    continue
                if detail_url := self._parse_search_page(response.text, candidate.normalized):
                    return detail_url
                remaining_budget = search_budget_seconds - (time.monotonic() - started)
                if remaining_budget <= 0:
                    break
                if detail_url := await self._resolve_detail_from_candidates(
                    response.text,
                    candidate.normalized,
                    time_budget_seconds=min(6.0, remaining_budget),
                ):
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

        cleaned_title = self._strip_number_prefix(title, number)
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
        values = [number, re.sub(r"[^0-9A-Za-z]", "", number)]
        if file_hint:
            for part in re.findall(r"[A-Za-z0-9]{4,}", file_hint):
                has_letter = any(char.isalpha() for char in part)
                has_digit = any(char.isdigit() for char in part)
                if has_letter and has_digit:
                    values.append(part)
        queries: list[str] = []
        seen: set[str] = set()
        for value in values:
            value = value.strip()
            if value and value not in seen:
                seen.add(value)
                queries.append(value)
            if len(queries) >= 4:
                break
        return queries

    def _build_search_requests(self, query: str) -> list[tuple[str, dict[str, str]]]:
        return [
            ("/search.php", {"content": query, "type": "1"}),
            ("/", {"s": query}),
        ]

    def _parse_search_page(self, html: str, expected_number: str) -> str | None:
        selector = Selector(text=html)
        for href, title in self._iter_search_results(selector):
            if title and self._matches_expected_number(expected_number, title):
                return urljoin(self.base_url, href)
        return None

    async def _resolve_detail_from_candidates(
        self,
        html: str,
        expected_number: str,
        *,
        time_budget_seconds: float,
    ) -> str | None:
        selector = Selector(text=html)
        client = await self.ensure_client()
        started = time.monotonic()
        for href, _title in self._iter_search_results(selector, limit=4):
            elapsed = time.monotonic() - started
            if elapsed >= time_budget_seconds:
                break
            request_timeout = max(2.0, min(self.timeout, time_budget_seconds - elapsed))
            detail_url = urljoin(self.base_url, href)
            try:
                response = await client.get(detail_url, follow_redirects=True, timeout=request_timeout)
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            detail_selector = Selector(text=response.text)
            title = self._extract_title(detail_selector)
            detail_number = self._extract_number(title) or self._extract_number(detail_url)
            if detail_number and self._matches_expected_number(expected_number, detail_number):
                return detail_url
        return None

    def _iter_search_results(self, selector: Selector, *, limit: int | None = None) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        seen: set[str] = set()
        for link in selector.css(
            ".xx-thumb, .xx-filmtxt h5 a, article h2 a, .entry-title a, .post-title a, .video-item a"
        ):
            href = link.attrib.get("href")
            if not href or href in seen:
                continue
            seen.add(href)
            results.append((href, self._extract_search_title(link)))
            if limit is not None and len(results) >= limit:
                break
        return results

    def _extract_search_title(self, link) -> str:
        text_candidates = [
            link.attrib.get("title", ""),
            link.attrib.get("alt", ""),
            _clean_text(" ".join(link.css("::text").getall())),
            _clean_text(" ".join(link.css("img::attr(alt)").getall())),
        ]
        for value in text_candidates:
            value = _clean_text(value)
            if value:
                return value
        return ""

    def _extract_title(self, selector: Selector) -> str:
        for css in ("h1.entry-title::text", "h1.post-title::text", ".xx-info-box h1::text", "h1::text", "title::text"):
            value = _clean_text(selector.css(css).get(""))
            if value and "404" not in value.lower() and "搜索结果" not in value:
                return value
        return ""

    def _extract_outline(self, selector: Selector) -> str:
        for css in (
            ".xx-video-desc::text",
            ".entry-content p::text",
            ".post-content p::text",
            ".video-content p::text",
            ".desc::text",
        ):
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
        for css in (
            ".xx-info-meta a::text",
            ".studio::text",
            ".maker::text",
            ".company::text",
            ".producer::text",
        ):
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
        for src in selector.css("meta[property='og:image']::attr(content), meta[name='twitter:image']::attr(content)").getall():
            full_url = urljoin(detail_url, src)
            if full_url in seen or not self._looks_like_media_image(full_url):
                continue
            seen.add(full_url)
            images.append(ImageAsset(url=full_url, kind="poster"))
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

    def _strip_number_prefix(self, title: str, number: str) -> str:
        title_clean = _clean_text(title)
        candidates = {
            number.upper(),
            number.replace("-", "").upper(),
        }
        for token in candidates:
            if title_clean.upper().startswith(token):
                return title_clean[len(token):].strip(" -_[]【】")
        return title_clean

    def _matches_expected_number(self, expected: str, actual_text: str) -> bool:
        return bool(self._normalize_tokens(expected) & self._normalize_tokens(actual_text))

    def _normalize_tokens(self, value: str) -> set[str]:
        tokens: set[str] = set()
        raw_parts = [part.upper() for part in re.split(r"[^0-9A-Za-z]+", value) if part]
        compact = re.sub(r"[^0-9A-Za-z]", "", value).upper()
        if compact:
            raw_parts.append(compact)

        for part in raw_parts:
            tokens.add(part)
            for match in re.finditer(r"([A-Z0-9]*?[A-Z][A-Z0-9]*?)(\d{2,5})", part):
                prefix, digits = match.groups()
                tokens.add(f"{prefix}{digits}")
                tokens.add(f"{prefix}{digits.lstrip('0') or '0'}")
                tokens.add(f"{prefix}-{digits.zfill(max(3, len(digits)))}")
        return tokens
