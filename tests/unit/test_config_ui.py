from __future__ import annotations

from mdcn.app.config_ui import build_config_from_ui_payload, render_config_ui_html


def test_build_config_from_ui_payload_maps_fields():
    payload = {
        "source_dir": "/data/failed",
        "target_root": "/data/library",
        "folder_template": "{number} {title}",
        "max_images": 5,
        "extensions": ".mp4, .mkv, .ts",
        "proxy": "http://127.0.0.1:7890",
        "timeout": 25,
        "retries": 4,
        "write_nfo": True,
        "write_json": False,
        "site_madouqu_enabled": True,
        "site_madouqu_base_url": "https://madouqu.cc",
        "site_mdtv_enabled": False,
        "site_mdtv_base_url": "https://www.mdpjzip.xyz",
    }

    config = build_config_from_ui_payload(payload)

    assert str(config.paths.source_dir) == "/data/failed"
    assert str(config.paths.target_root) == "/data/library"
    assert config.output.max_images == 5
    assert config.output.write_json is False
    assert config.scanner.extensions == (".mp4", ".mkv", ".ts")
    assert config.sites["mdtv"].enabled is False


def test_render_config_ui_html_contains_expected_controls():
    html = render_config_ui_html()

    assert "Config Studio" in html
    assert 'id="source_dir"' in html
    assert 'id="target_root"' in html
    assert 'id="folder_template"' in html
    assert 'id="site_madouqu_base_url"' in html
