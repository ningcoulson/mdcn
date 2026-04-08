"""Metadata serialization."""

from __future__ import annotations

from mdcn.domain.models import MetadataResult


def serialize_metadata(result: MetadataResult) -> dict[str, object]:
    return {
        "number": result.number,
        "title": result.title,
        "outline": result.outline,
        "actors": result.actors,
        "tags": result.tags,
        "studio": result.studio,
        "publisher": result.publisher,
        "series": result.series,
        "country": result.country,
        "release_date": result.release_date.isoformat() if result.release_date else None,
        "year": result.year,
        "website": result.website,
        "source": result.source,
        "images": [
            {
                "url": image.url,
                "kind": image.kind,
                "local_path": str(image.local_path) if image.local_path else None,
                "width": image.width,
                "height": image.height,
            }
            for image in result.images
        ],
        "extras": result.extras,
    }
