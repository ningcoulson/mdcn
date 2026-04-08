"""Output naming rules."""

from __future__ import annotations

from pathlib import Path


def sanitize_path_component(text: str) -> str:
    value = text.strip()
    for char in '<>:"\\|?*':
        value = value.replace(char, " ")
    value = value.replace("/", " ")
    value = " ".join(value.split())
    return value.rstrip(". ")


def build_folder_name(number: str, title: str) -> str:
    safe_number = sanitize_path_component(number)
    safe_title = sanitize_path_component(title)
    if safe_number and safe_title:
        return f"{safe_number} {safe_title}"
    return safe_number or safe_title or "unknown"


def build_image_filename(number: str, kind: str, index: int = 1, url: str = "") -> str:
    suffix = Path(url).suffix if url else ""
    suffix = suffix.split("?")[0] if suffix else ""
    if not suffix:
        suffix = ".jpg"
    base = sanitize_path_component(number).replace(" ", "_") or "unknown"
    asset_kind = sanitize_path_component(kind).replace(" ", "_") or "image"
    if index > 1:
        return f"{base}_{asset_kind}_{index}{suffix}"
    return f"{base}_{asset_kind}{suffix}"
