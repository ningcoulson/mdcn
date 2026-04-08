from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mdcn.domain.models import ImageAsset, MetadataResult
from mdcn.pipeline.resources import ResourcePipeline


@pytest.mark.asyncio
async def test_resource_pipeline_downloads_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"img")

    from mdcn import network as network_pkg
    from mdcn.pipeline import resources as resources_module

    def build_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(network_pkg, "build_async_client", build_client)
    monkeypatch.setattr(resources_module, "build_async_client", build_client)

    result = MetadataResult(
        number="MD-001",
        title="Title",
        images=[
            ImageAsset(url="https://example.com/poster.jpg", kind="poster"),
            ImageAsset(url="https://example.com/fanart.jpg", kind="extrafanart"),
        ],
    )

    pipeline = ResourcePipeline(max_images=2)
    processed = await pipeline.process(result, tmp_path)

    assert processed.images[0].local_path is not None
    assert processed.images[0].local_path.read_bytes() == b"img"
    assert processed.images[1].local_path is not None


@pytest.mark.asyncio
async def test_resource_pipeline_retries_transient_download_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(502, content=b"bad")
        return httpx.Response(200, content=b"img")

    from mdcn import network as network_pkg
    from mdcn.pipeline import resources as resources_module

    def build_client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(network_pkg, "build_async_client", build_client)
    monkeypatch.setattr(resources_module, "build_async_client", build_client)

    result = MetadataResult(
        number="MD-001",
        title="Title",
        images=[ImageAsset(url="https://example.com/poster.jpg", kind="poster")],
    )

    pipeline = ResourcePipeline(max_images=1, retries=1)
    processed = await pipeline.process(result, tmp_path)

    assert attempts["count"] == 2
    assert processed.images[0].local_path is not None
