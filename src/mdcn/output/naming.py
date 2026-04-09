"""Output naming rules."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DEFAULT_FOLDER_TEMPLATE = "{number} {title}"
_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def sanitize_path_component(text: str) -> str:
    value = text.strip()
    for char in '<>:"\\|?*':
        value = value.replace(char, " ")
    value = value.replace("/", " ")
    value = " ".join(value.split())
    return value.rstrip(". ")


def build_template_context(**values: Any) -> dict[str, str]:
    context: dict[str, str] = {}
    for key, value in values.items():
        if isinstance(value, list):
            context[key] = ", ".join(str(item) for item in value if str(item).strip())
            continue
        if value is None:
            context[key] = ""
            continue
        context[key] = str(value)
    return context


def render_folder_template(template: str, context: dict[str, Any]) -> str:
    source = template.strip() or DEFAULT_FOLDER_TEMPLATE
    safe_context = build_template_context(**context)

    def replace_token(match: re.Match[str]) -> str:
        return safe_context.get(match.group(1), "")

    rendered = _TOKEN_RE.sub(replace_token, source)
    parts = [sanitize_path_component(part) for part in rendered.replace("\\", "/").split("/")]
    clean_parts = [part for part in parts if part]
    if clean_parts:
        return "/".join(clean_parts)

    fallback = sanitize_path_component(safe_context.get("number", ""))
    if fallback:
        return fallback
    fallback = sanitize_path_component(safe_context.get("title", ""))
    return fallback or "unknown"


def build_folder_name(number: str, title: str, template: str = DEFAULT_FOLDER_TEMPLATE, **extra: Any) -> str:
    context = build_template_context(number=number, title=title, **extra)
    return render_folder_template(template, context)


def build_folder_path(number: str, title: str, template: str = DEFAULT_FOLDER_TEMPLATE, **extra: Any) -> Path:
    folder_name = build_folder_name(number, title, template, **extra)
    return Path(*folder_name.split("/"))


def preview_folder_name(template: str, **sample: Any) -> str:
    default_sample = {
        "number": "MD-001",
        "title": "Sample Title",
        "studio": "Madou",
        "series": "Series Name",
        "source": "madouqu",
        "year": "2024",
        "actors": ["Performer A", "Performer B"],
    }
    default_sample.update(sample)
    return render_folder_template(template, default_sample)


def build_video_filename(number: str, title: str, suffix: str, template: str = DEFAULT_FOLDER_TEMPLATE, **extra: Any) -> str:
    rendered = build_folder_name(number, title, template, **extra)
    basename = sanitize_path_component(rendered.split("/")[-1]) if rendered else ""
    if not basename:
        basename = sanitize_path_component(number) or sanitize_path_component(title) or "unknown"
    final_suffix = suffix or ".mp4"
    if not final_suffix.startswith("."):
        final_suffix = "." + final_suffix
    return f"{basename}{final_suffix}"


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
