from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mdcn2.domain.models import ImageAsset, MetadataResult
from mdcn2.pipeline.resources import ResourcePipeline


@pytest.mark.asyncio
async def test_resource_pipeline_downloads_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"img")

    from mdcn2 import pipeline as pipeline_pkg
    from mdcn2 import network as network_pkg
    from mdcn2.pipeline import resources as resources_module

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
