"""Retry helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def run_with_retries(
    func: Callable[[], Awaitable[T]],
    *,
    retries: int = 2,
    delay_seconds: float = 0.5,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await func()
        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, retry_exceptions):
                raise
            last_exc = exc
            if attempt >= retries:
                break
            await asyncio.sleep(delay_seconds)
    assert last_exc is not None
    raise last_exc
