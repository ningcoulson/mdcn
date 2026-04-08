"""Resource download pipeline."""

from __future__ import annotations

from pathlib import Path

from mdcn2.domain.models import MetadataResult
from mdcn2.network.client import build_async_client
from mdcn2.output.naming import build_image_filename


class ResourcePipeline:
    def __init__(self, *, proxy: str | None = None, timeout: float = 20.0, max_images: int = 6) -> None:
        self.proxy = proxy
        self.timeout = timeout
        self.max_images = max_images

    async def process(self, result: MetadataResult, target_dir: Path) -> MetadataResult:
        if not result.images:
            return result

        target_dir.mkdir(parents=True, exist_ok=True)
        async with build_async_client(proxy=self.proxy, timeout=self.timeout) as client:
            for index, image in enumerate(result.images[: self.max_images], start=1):
                filename = build_image_filename(result.number or result.title, image.kind, index=index, url=image.url)
                destination = target_dir / filename
                response = await client.get(image.url)
                response.raise_for_status()
                destination.write_bytes(response.content)
                image.local_path = destination
        return result
