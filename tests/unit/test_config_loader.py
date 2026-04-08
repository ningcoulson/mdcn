from __future__ import annotations

from pathlib import Path

import pytest

from mdcn.config.loader import config_to_dict, load_config, render_config_toml, save_config
from mdcn.config.models import AppConfig, NetworkConfig, OutputConfig, PathsConfig, ScannerConfig, SiteConfig
from mdcn.domain.errors import ConfigError


def test_load_config_reads_basic_toml(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[source]
dir = "/data/failed"

[target]
root = "/data/library"

[output]
max_images = 8

[scanner]
extensions = [".mp4", ".mkv"]

[sites.madouqu]
enabled = true
base_url = "https://madouqu.cc"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.paths.source_dir == Path("/data/failed")
    assert config.paths.target_root == Path("/data/library")
    assert config.output.max_images == 8
    assert config.scanner.normalized_extensions() == {".mp4", ".mkv"}
    assert config.sites["madouqu"].base_url == "https://madouqu.cc"


def test_load_config_raises_for_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.toml")


def test_load_config_requires_source_and_target(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[source]\ndir = \"/data/failed\"\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_save_config_round_trip(tmp_path: Path):
    config = AppConfig(
        paths=PathsConfig(source_dir=Path("/data/inbox"), target_root=Path("/data/library")),
        output=OutputConfig(max_images=8, folder_template="{number}-{title}"),
        network=NetworkConfig(proxy="http://127.0.0.1:7890", timeout=30.0, retries=3),
        scanner=ScannerConfig(extensions=(".mp4", ".mkv")),
        sites={
            "madouqu": SiteConfig(enabled=True, base_url="https://madouqu.cc"),
            "mdtv": SiteConfig(enabled=False, base_url="https://mdtv.example"),
        },
    )
    path = tmp_path / "config.toml"

    save_config(config, path)
    loaded = load_config(path)

    assert loaded.paths.source_dir == Path("/data/inbox")
    assert loaded.output.folder_template == "{number}-{title}"
    assert loaded.network.proxy == "http://127.0.0.1:7890"
    assert loaded.sites["mdtv"].enabled is False


def test_render_config_toml_contains_sections():
    config = AppConfig(
        paths=PathsConfig(source_dir=Path("/a"), target_root=Path("/b")),
        sites={"madouqu": SiteConfig(enabled=True, base_url="https://madouqu.cc")},
    )

    content = render_config_toml(config)

    assert "[source]" in content
    assert '[sites.madouqu]' in content
    assert 'dir = "/a"' in content
