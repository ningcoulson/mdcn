"""NFO rendering helpers."""

from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring

from mdcn2.domain.models import MetadataResult


def build_nfo_xml(result: MetadataResult) -> str:
    movie = Element("movie")
    _set_text(movie, "title", result.title)
    _set_text(movie, "originaltitle", result.title)
    _set_text(movie, "sorttitle", result.number or result.title)
    _set_text(movie, "plot", result.outline)
    _set_text(movie, "country", result.country)
    _set_text(movie, "studio", result.studio)
    _set_text(movie, "premiered", result.release_date.isoformat() if result.release_date else "")
    _set_text(movie, "year", str(result.year) if result.year else "")
    _set_text(movie, "id", result.number)
    _set_text(movie, "num", result.number)
    _set_text(movie, "source", result.source)
    _set_text(movie, "website", result.website)

    for tag in result.tags:
        _set_text(movie, "tag", tag)

    for actor_name in result.actors:
        actor = SubElement(movie, "actor")
        _set_text(actor, "name", actor_name)

    xml = tostring(movie, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n"


def _set_text(parent: Element, tag: str, value: str) -> None:
    child = SubElement(parent, tag)
    child.text = value
