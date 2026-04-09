from __future__ import annotations

from mdcn.app.config_ui import ConfigUiRunState, build_config_from_ui_payload, render_config_ui_html


def test_build_config_from_ui_payload_maps_fields():
    payload = {
        "source_dir": "/data/failed",
        "target_root": "/data/library",
        "folder_template": "{number} {title}",
        "max_images": 5,
        "extensions": ".mp4, .mkv, .ts",
        "site_order": "avjia, tianmei, madouqu",
        "proxy": "http://127.0.0.1:7890",
        "timeout": 25,
        "retries": 4,
        "write_nfo": True,
        "write_json": False,
        "site_madouqu_enabled": True,
        "site_madouqu_base_url": "https://madouqu.cc",
        "site_madouqu_mirrors": "https://mq1.example, https://mq2.example",
        "site_mdtv_enabled": False,
        "site_mdtv_base_url": "https://www.mdpjzip.xyz",
        "site_mdtv_mirrors": "https://mdtv-mirror.example",
        "site_madouclub_enabled": True,
        "site_madouclub_base_url": "https://madou.club",
        "site_madouclub_mirrors": "",
        "site_avjia_enabled": True,
        "site_avjia_base_url": "https://avjia.net",
        "site_avjia_mirrors": "https://avjia-mirror.example",
        "site_tianmei_enabled": True,
        "site_tianmei_base_url": "https://www.94mt.cc",
        "site_tianmei_mirrors": "https://www.wyxk.cc, https://www.xbyc.cc",
    }

    config = build_config_from_ui_payload(payload)

    assert str(config.paths.source_dir) == "/data/failed"
    assert str(config.paths.target_root) == "/data/library"
    assert config.output.max_images == 5
    assert config.output.write_json is False
    assert config.scanner.extensions == (".mp4", ".mkv", ".ts")
    assert config.priority.site_order == ("avjia", "tianmei", "madouqu")
    assert config.sites["mdtv"].enabled is False
    assert config.sites["madouclub"].base_url == "https://madou.club"
    assert config.sites["avjia"].base_url == "https://avjia.net"
    assert config.sites["tianmei"].base_url == "https://www.94mt.cc"
    assert config.sites["madouqu"].mirrors == ("https://mq1.example", "https://mq2.example")
    assert config.sites["avjia"].mirrors == ("https://avjia-mirror.example",)
    assert config.sites["tianmei"].mirrors == ("https://www.wyxk.cc", "https://www.xbyc.cc")


def test_render_config_ui_html_contains_expected_controls():
    html = render_config_ui_html()

    assert "Config Studio" in html
    assert 'id="source_dir"' in html
    assert 'id="target_root"' in html
    assert 'id="folder_template"' in html
    assert 'id="site_order"' in html
    assert 'id="previewText"' in html
    assert 'id="runButton"' in html
    assert 'id="retryFailedButton"' in html
    assert 'id="taskList"' in html
    assert 'id="refreshTasksButton"' in html
    assert 'id="taskSearch"' in html
    assert 'id="taskDetailDialog"' in html
    assert 'id="site_madouqu_base_url"' in html
    assert 'id="site_madouqu_mirrors"' in html
    assert 'id="site_madouclub_base_url"' in html
    assert 'id="site_mdtv_mirrors"' in html
    assert 'id="site_avjia_base_url"' in html
    assert 'id="site_avjia_mirrors"' in html
    assert 'id="site_tianmei_base_url"' in html
    assert 'id="site_tianmei_mirrors"' in html


def test_config_ui_run_state_tracks_lifecycle():
    state = ConfigUiRunState()

    assert state.start("scrape") is True
    assert state.start("scrape") is False
    snapshot = state.snapshot()
    assert snapshot["running"] is True
    assert snapshot["mode"] == "scrape"

    state.finish("scrape", {"scanned": 3, "succeeded": 2, "failed": 1, "skipped": 0})
    finished = state.snapshot()
    assert finished["running"] is False
    assert finished["last_stats"]["succeeded"] == 2
    assert finished["message"] == "Scrape finished"
