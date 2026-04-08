from __future__ import annotations

from pathlib import Path

import pytest

from mdcn2.config.loader import load_config
from mdcn2.domain.errors import ConfigError


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
