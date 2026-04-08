"""Configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mdcn.domain.errors import ConfigError

from .models import AppConfig, NetworkConfig, OutputConfig, PathsConfig, ScannerConfig, SiteConfig

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"config file not found: {config_path}")
    if tomllib is None:  # pragma: no cover
        raise ConfigError("tomllib is unavailable; Python 3.11+ is required")

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return _build_config(data)


def save_config(config: AppConfig, path: str | Path) -> Path:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(render_config_toml(config), encoding="utf-8")
    return config_path


def config_to_dict(config: AppConfig) -> dict[str, Any]:
    return {
        "source": {"dir": str(config.paths.source_dir)},
        "target": {"root": str(config.paths.target_root)},
        "output": {
            "max_images": config.output.max_images,
            "write_nfo": config.output.write_nfo,
            "write_json": config.output.write_json,
            "folder_template": config.output.folder_template,
        },
        "network": {
            "proxy": config.network.proxy or "",
            "timeout": config.network.timeout,
            "retries": config.network.retries,
        },
        "scanner": {"extensions": list(config.scanner.extensions)},
        "sites": {
            name: {
                "enabled": site.enabled,
                "base_url": site.base_url,
            }
            for name, site in config.sites.items()
        },
    }


def render_config_toml(config: AppConfig) -> str:
    data = config_to_dict(config)
    lines: list[str] = []

    lines.extend(["[source]", f'dir = "{_escape_toml_string(data["source"]["dir"])}"', ""])
    lines.extend(["[target]", f'root = "{_escape_toml_string(data["target"]["root"])}"', ""])

    output = data["output"]
    lines.extend(
        [
            "[output]",
            f"max_images = {output['max_images']}",
            f"write_nfo = {_bool_str(output['write_nfo'])}",
            f"write_json = {_bool_str(output['write_json'])}",
            f'folder_template = "{_escape_toml_string(output["folder_template"])}"',
            "",
        ]
    )

    network = data["network"]
    lines.extend(
        [
            "[network]",
            f'proxy = "{_escape_toml_string(network["proxy"])}"',
            f"timeout = {network['timeout']}",
            f"retries = {network['retries']}",
            "",
        ]
    )

    scanner = data["scanner"]
    lines.extend(["[scanner]", f"extensions = [{', '.join(_quote(item) for item in scanner['extensions'])}]", ""])

    sites = data["sites"]
    for name in sorted(sites):
        site = sites[name]
        lines.extend(
            [
                f"[sites.{name}]",
                f"enabled = {_bool_str(site['enabled'])}",
                f'base_url = "{_escape_toml_string(site["base_url"])}"',
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def _build_config(data: dict[str, Any]) -> AppConfig:
    source = data.get("source", {})
    target = data.get("target", {})
    paths = PathsConfig(
        source_dir=_require_path(source, "dir", "source.dir"),
        target_root=_require_path(target, "root", "target.root"),
    )

    output_raw = data.get("output", {})
    output = OutputConfig(
        max_images=int(output_raw.get("max_images", 6)),
        write_nfo=bool(output_raw.get("write_nfo", True)),
        write_json=bool(output_raw.get("write_json", True)),
        folder_template=str(output_raw.get("folder_template", "{number} {title}")),
    )

    network_raw = data.get("network", {})
    network = NetworkConfig(
        proxy=_optional_str(network_raw.get("proxy")),
        timeout=float(network_raw.get("timeout", 20.0)),
        retries=int(network_raw.get("retries", 2)),
    )

    scanner_raw = data.get("scanner", {})
    scanner = ScannerConfig(
        extensions=tuple(str(ext) for ext in scanner_raw.get("extensions", ScannerConfig().extensions)),
    )

    sites_raw = data.get("sites", {})
    sites: dict[str, SiteConfig] = {}
    for name, raw in sites_raw.items():
        if not isinstance(raw, dict):
            raise ConfigError(f"sites.{name} must be a table")
        sites[name] = SiteConfig(
            enabled=bool(raw.get("enabled", True)),
            base_url=str(raw.get("base_url", "")),
        )

    return AppConfig(
        paths=paths,
        output=output,
        network=network,
        scanner=scanner,
        sites=sites,
    )


def build_config_from_dict(data: dict[str, Any]) -> AppConfig:
    return _build_config(data)


def _require_path(section: dict[str, Any], key: str, label: str) -> Path:
    value = section.get(key)
    if not value or not isinstance(value, str):
        raise ConfigError(f"missing required config value: {label}")
    return Path(value)


def _optional_str(value: Any) -> str | None:
    if value in ("", None):
        return None
    return str(value)


def _escape_toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _quote(value: str) -> str:
    return f'"{_escape_toml_string(value)}"'


def _bool_str(value: bool) -> str:
    return "true" if value else "false"
