"""Base crawler abstraction."""

from __future__ import annotations

import abc
from urllib.parse import urljoin

import httpx

from mdcn.domain.errors import NetworkError, ParseError
from mdcn.domain.models import MetadataResult, NumberCandidate
from mdcn.network.client import build_async_client
from mdcn.network.retry import run_with_retries


class BaseCrawler(abc.ABC):
    def __init__(
        self,
        *,
        base_url: str | None = None,
        mirrors: tuple[str, ...] | list[str] | None = None,
        client: httpx.AsyncClient | None = None,
        proxy: str | None = None,
        timeout: float = 20.0,
        retries: int = 2,
    ) -> None:
        self.base_url = base_url or self.default_base_url
        self._base_urls = self._collect_base_urls(self.base_url, mirrors)
        self._client = client
        self.proxy = proxy
        self.timeout = timeout
        self.retries = retries

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def default_base_url(self) -> str:
        ...

    @property
    def healthcheck_path(self) -> str:
        return "/"

    async def ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = build_async_client(proxy=self.proxy, timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def run(self, candidate: NumberCandidate, *, file_hint: str = "") -> MetadataResult:
        detail_url = await self.search(candidate, file_hint=file_hint)
        html = await self.fetch(detail_url)
        result = await self.parse(html, detail_url, candidate, file_hint=file_hint)
        if not result.number:
            raise ParseError(f"{self.name} returned empty number")
        result.source = self.name
        result.website = detail_url
        return result

    async def search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        await self.resolve_base_url()
        return await run_with_retries(
            lambda: self._search(candidate, file_hint=file_hint),
            retries=self.retries,
            delay_seconds=0.4,
            retry_exceptions=(httpx.HTTPError, TimeoutError, NetworkError),
        )

    async def fetch(self, url: str) -> str:
        client = await self.ensure_client()
        try:
            async def do_fetch() -> httpx.Response:
                response = await client.get(url)
                response.raise_for_status()
                return response

            response = await run_with_retries(
                do_fetch,
                retries=self.retries,
                delay_seconds=0.4,
                retry_exceptions=(httpx.HTTPError, TimeoutError),
            )
        except httpx.HTTPError as exc:
            raise NetworkError(f"{self.name} failed to fetch {url}: {exc}") from exc
        return response.text

    async def resolve_base_url(self) -> str:
        if len(self._base_urls) <= 1:
            self.base_url = self._base_urls[0]
            return self.base_url

        for candidate in self._base_urls:
            if await self.check_health(candidate):
                self.base_url = candidate
                return candidate

        self.base_url = self._base_urls[0]
        return self.base_url

    async def check_health(self, base_url: str) -> bool:
        client = await self.ensure_client()
        health_url = urljoin(base_url.rstrip("/") + "/", self.healthcheck_path.lstrip("/"))
        try:
            response = await client.get(health_url, follow_redirects=True)
        except httpx.HTTPError:
            return False
        return 200 <= response.status_code < 500

    def candidate_base_urls(self) -> tuple[str, ...]:
        return self._base_urls

    def _collect_base_urls(
        self,
        primary: str,
        mirrors: tuple[str, ...] | list[str] | None,
    ) -> tuple[str, ...]:
        ordered: list[str] = []
        for value in (primary, *(mirrors or ())):
            value = value.strip()
            if value and value not in ordered:
                ordered.append(value)
        return tuple(ordered)

    @abc.abstractmethod
    async def _search(self, candidate: NumberCandidate, *, file_hint: str = "") -> str:
        ...

    @abc.abstractmethod
    async def parse(
        self,
        html: str,
        url: str,
        candidate: NumberCandidate,
        *,
        file_hint: str = "",
    ) -> MetadataResult:
        ...
