"""Base crawler abstraction."""

from __future__ import annotations

import abc

import httpx

from mdcn2.domain.errors import NetworkError, ParseError
from mdcn2.domain.models import MetadataResult, NumberCandidate
from mdcn2.network.client import build_async_client


class BaseCrawler(abc.ABC):
    def __init__(self, *, base_url: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url or self.default_base_url
        self._client = client

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def default_base_url(self) -> str:
        ...

    async def ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = build_async_client()
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
        return await self._search(candidate, file_hint=file_hint)

    async def fetch(self, url: str) -> str:
        client = await self.ensure_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NetworkError(f"{self.name} failed to fetch {url}: {exc}") from exc
        return response.text

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
