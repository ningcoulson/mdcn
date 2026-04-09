"""Resource download pipeline."""

from __future__ import annotations

import re
from pathlib import Path

from mdcn.domain.models import MetadataResult
from mdcn.network.client import build_async_client
from mdcn.network.retry import run_with_retries
from mdcn.output.naming import build_image_filename


class ResourcePipeline:
    def __init__(self, *, proxy: str | None = None, timeout: float = 20.0, retries: int = 2, max_images: int = 6) -> None:
        self.proxy = proxy
        self.timeout = timeout
        self.retries = retries
        self.max_images = max_images

    async def process(self, result: MetadataResult, target_dir: Path) -> MetadataResult:
        if not result.images:
            return result

        target_dir.mkdir(parents=True, exist_ok=True)
        counters: dict[str, int] = {}
        canonical_poster_path: Path | None = None
        async with build_async_client(proxy=self.proxy, timeout=self.timeout) as client:
            for image in result.images[: self.max_images]:
                kind = (image.kind or "image").strip().lower()
                if kind == "poster" and counters.get("poster", 0) >= 1:
                    continue
                index = counters.get(kind, 0) + 1
                counters[kind] = index
                filename = build_image_filename(result.number or result.title, image.kind, index=index, url=image.url)
                destination = target_dir / filename
                try:
                    async def do_download() -> object:
                        response = await client.get(image.url, follow_redirects=True)
                        response.raise_for_status()
                        return response

                    response = await run_with_retries(
                        do_download,
                        retries=self.retries,
                        delay_seconds=0.4,
                    )
                except Exception:  # noqa: BLE001
                    continue

                destination.write_bytes(response.content)
                image.local_path = destination
                if kind == "poster":
                    canonical_poster_path = destination
        self._cleanup_legacy_posters(target_dir, canonical_poster_path)
        return result

    def _cleanup_legacy_posters(self, target_dir: Path, canonical_poster_path: Path | None) -> None:
        if canonical_poster_path is None:
            return
        poster_pattern = re.compile(r"(?i)^(poster|.+_poster(?:_\d+)?)\.[a-z0-9]+$")
        canonical_name = canonical_poster_path.name
        for path in target_dir.iterdir():
            if not path.is_file():
                continue
            if path.name == canonical_name:
                continue
            if poster_pattern.match(path.name):
                path.unlink(missing_ok=True)
