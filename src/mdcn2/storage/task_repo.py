"""SQLite-backed task tracking."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class TaskRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_path TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    number TEXT DEFAULT '',
                    source TEXT DEFAULT '',
                    target_dir TEXT DEFAULT '',
                    reason TEXT DEFAULT '',
                    detail TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def was_processed(self, video_path: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM tasks WHERE video_path = ?",
                (video_path,),
            ).fetchone()
        return bool(row and row[0] == "success")

    def start_task(self, video_path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks(video_path, status, updated_at)
                VALUES(?, 'running', CURRENT_TIMESTAMP)
                ON CONFLICT(video_path) DO UPDATE SET
                    status = 'running',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (video_path,),
            )

    def mark_success(self, video_path: str, *, source: str, number: str, target_dir: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks(video_path, status, number, source, target_dir, updated_at)
                VALUES(?, 'success', ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(video_path) DO UPDATE SET
                    status = 'success',
                    number = excluded.number,
                    source = excluded.source,
                    target_dir = excluded.target_dir,
                    reason = '',
                    detail = '',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (video_path, number, source, target_dir),
            )

    def mark_failure(self, video_path: str, *, reason: str, detail: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks(video_path, status, reason, detail, updated_at)
                VALUES(?, 'failed', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(video_path) DO UPDATE SET
                    status = 'failed',
                    reason = excluded.reason,
                    detail = excluded.detail,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (video_path, reason, detail),
            )

    def summary(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall()
        return {status: count for status, count in rows}
