from __future__ import annotations

from pathlib import Path

from mdcn2.storage.task_repo import TaskRepository


def test_task_repo_tracks_success_and_failure(tmp_path: Path):
    repo = TaskRepository(tmp_path / "tasks.db")

    repo.start_task("/videos/MD-001.mp4")
    repo.mark_failure("/videos/MD-001.mp4", reason="no_match", detail="not found")
    repo.start_task("/videos/MD-002.mp4")
    repo.mark_success("/videos/MD-002.mp4", source="madouqu", number="MD-002", target_dir="/library/MD-002")

    assert repo.was_processed("/videos/MD-001.mp4") is False
    assert repo.was_processed("/videos/MD-002.mp4") is True
    assert repo.summary()["failed"] == 1
    assert repo.summary()["success"] == 1
