from __future__ import annotations

from pathlib import Path

from mdcn.app.cli import main
from mdcn.config.loader import save_config
from mdcn.config.models import AppConfig, PathsConfig
from mdcn.storage.task_repo import TaskRepository


def test_cli_tasks_lists_recent_records(tmp_path: Path, capsys, monkeypatch):
    source_dir = tmp_path / "failed"
    target_root = tmp_path / "library"
    source_dir.mkdir()
    target_root.mkdir()

    config = AppConfig(paths=PathsConfig(source_dir=source_dir, target_root=target_root))
    config_path = tmp_path / "config.toml"
    save_config(config, config_path)

    repo = TaskRepository(target_root / ".mdcn" / "tasks.db")
    repo.mark_failure("/videos/MD-001.mp4", reason="no_match", detail="not found")
    repo.mark_success("/videos/MD-002.mp4", source="madouqu", number="MD-002", target_dir="/library/MD-002")

    monkeypatch.setattr("sys.argv", ["mdcn", "tasks", "--config", str(config_path), "--status", "failed"])
    exit_code = main()

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "[failed] /videos/MD-001.mp4" in captured
    assert "not found" in captured
