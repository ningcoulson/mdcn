"""Shared HTTP client creation."""

from __future__ import annotations

import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def build_async_client(
    *,
    proxy: str | None = None,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
    **kwargs: object,
) -> httpx.AsyncClient:
    final_headers = dict(DEFAULT_HEADERS)
    if headers:
        final_headers.update(headers)
    return httpx.AsyncClient(proxy=proxy, timeout=timeout, headers=final_headers, **kwargs)
