from __future__ import annotations

from pathlib import Path
from subprocess import CalledProcessError

from mdcn.app.config_ui import (
    ConfigUiRunState,
    _open_browser_url,
    build_config_from_ui_payload,
    pick_directory,
    render_config_ui_html,
    validate_path_settings,
)


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
    assert 'id="pathStatusText"' in html
    assert 'id="browseSourceButton"' in html
    assert 'id="browseTargetButton"' in html
    assert 'id="folder_template"' in html
    assert 'id="site_order"' in html
    assert 'id="previewText"' in html
    assert 'id="runButton"' in html
    assert 'id="retryFailedButton"' in html
    assert 'id="taskList"' in html
    assert 'id="refreshTasksButton"' in html
    assert 'id="taskSearch"' in html
    assert 'id="taskDetailDialog"' in html
    assert 'id="welcomeNotice"' in html
    assert 'id="welcomeAlert"' in html
    assert 'id="site_madouqu_base_url"' in html
    assert 'id="site_madouqu_mirrors"' in html
    assert 'id="site_madouclub_base_url"' in html
    assert 'id="site_mdtv_mirrors"' in html
    assert 'id="site_avjia_base_url"' in html
    assert 'id="site_avjia_mirrors"' in html
    assert 'id="site_tianmei_base_url"' in html
    assert 'id="site_tianmei_mirrors"' in html
    assert "保存并开始刮削" in html


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


def test_validate_path_settings_reports_ready_paths(tmp_path: Path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    target_dir = tmp_path / "library"

    result = validate_path_settings(str(source_dir), str(target_dir))

    assert result["source_ready"] is True
    assert result["target_ready"] is True
    assert result["can_run"] is True
    assert "存在" in result["source_message"]
    assert "可以在" in result["target_message"]


def test_validate_path_settings_reports_missing_source(tmp_path: Path):
    target_dir = tmp_path / "library"

    result = validate_path_settings(str(tmp_path / "missing"), str(target_dir))

    assert result["source_ready"] is False
    assert result["can_run"] is False
    assert "不存在" in result["source_message"]


def test_pick_directory_uses_macos_picker(monkeypatch):
    calls: list[list[str]] = []

    class Result:
        stdout = "/Users/demo/Movies\n"

    def fake_run(command, check, capture_output, text):
        calls.append(command)
        return Result()

    monkeypatch.setattr("mdcn.app.config_ui.platform.system", lambda: "Darwin")
    monkeypatch.setattr("mdcn.app.config_ui.subprocess.run", fake_run)

    selected = pick_directory("/Users/demo")

    assert selected == "/Users/demo/Movies"
    assert calls
    assert calls[0][0] == "osascript"


def test_pick_directory_returns_none_when_picker_is_cancelled(monkeypatch):
    def fake_run(command, check, capture_output, text):
        raise CalledProcessError(returncode=1, cmd=command)

    monkeypatch.setattr("mdcn.app.config_ui.platform.system", lambda: "Darwin")
    monkeypatch.setattr("mdcn.app.config_ui.subprocess.run", fake_run)

    selected = pick_directory("/Users/demo")

    assert selected is None


def test_open_browser_url_prefers_macos_open(monkeypatch):
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_run(command, check, capture_output, text):
        calls.append(command)
        return Result()

    monkeypatch.setattr("mdcn.app.config_ui.platform.system", lambda: "Darwin")
    monkeypatch.setattr("mdcn.app.config_ui.subprocess.run", fake_run)

    opened = _open_browser_url("http://127.0.0.1:8765")

    assert opened is True
    assert calls == [["open", "http://127.0.0.1:8765"]]


def test_open_browser_url_falls_back_to_webbrowser(monkeypatch):
    calls: list[list[str]] = []

    class Result:
        returncode = 1

    def fake_run(command, check, capture_output, text):
        calls.append(command)
        return Result()

    monkeypatch.setattr("mdcn.app.config_ui.platform.system", lambda: "Linux")
    monkeypatch.setattr("mdcn.app.config_ui.subprocess.run", fake_run)
    monkeypatch.setattr("mdcn.app.config_ui.webbrowser.open", lambda url, new, autoraise: True)

    opened = _open_browser_url("http://127.0.0.1:8765")

    assert opened is True
    assert calls == [["xdg-open", "http://127.0.0.1:8765"], ["gio", "open", "http://127.0.0.1:8765"]]
