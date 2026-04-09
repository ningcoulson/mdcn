"""SQLite-backed task tracking."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class TaskRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10.0)

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_path TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    number TEXT DEFAULT '',
                    title TEXT DEFAULT '',
                    source TEXT DEFAULT '',
                    target_dir TEXT DEFAULT '',
                    poster_path TEXT DEFAULT '',
                    reason TEXT DEFAULT '',
                    detail TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        self._ensure_column("title", "TEXT DEFAULT ''")
        self._ensure_column("poster_path", "TEXT DEFAULT ''")

    def _ensure_column(self, column_name: str, column_definition: str) -> None:
        with self._connection() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
            if column_name in columns:
                return
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {column_name} {column_definition}")

    def was_processed(self, video_path: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT status FROM tasks WHERE video_path = ?",
                (video_path,),
            ).fetchone()
        return bool(row and row[0] == "success")

    def start_task(self, video_path: str) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks(video_path, status, reason, detail, updated_at)
                VALUES(?, 'running', '', '', CURRENT_TIMESTAMP)
                ON CONFLICT(video_path) DO UPDATE SET
                    status = 'running',
                    reason = '',
                    detail = '',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (video_path,),
            )

    def mark_success(
        self,
        video_path: str,
        *,
        source: str,
        number: str,
        title: str = "",
        target_dir: str,
        poster_path: str = "",
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks(video_path, status, number, title, source, target_dir, poster_path, updated_at)
                VALUES(?, 'success', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(video_path) DO UPDATE SET
                    status = 'success',
                    number = excluded.number,
                    title = excluded.title,
                    source = excluded.source,
                    target_dir = excluded.target_dir,
                    poster_path = excluded.poster_path,
                    reason = '',
                    detail = '',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (video_path, number, title, source, target_dir, poster_path),
            )

    def mark_failure(self, video_path: str, *, reason: str, detail: str = "") -> None:
        with self._connection() as conn:
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

    def list_failed_video_paths(self) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT video_path
                FROM tasks
                WHERE status = 'failed'
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        return [row[0] for row in rows]

    def list_recent_tasks(
        self,
        limit: int = 10,
        status: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, str]]:
        with self._connection() as conn:
            conditions: list[str] = []
            params: list[str | int] = []
            if status and status != "all":
                conditions.append("status = ?")
                params.append(status)
            if query:
                like = f"%{query.strip()}%"
                conditions.append("(video_path LIKE ? OR number LIKE ? OR source LIKE ? OR reason LIKE ? OR detail LIKE ?)")
                params.extend([like, like, like, like, like])

            sql = """
                SELECT video_path, status, number, title, source, target_dir, poster_path, reason, detail, updated_at
                FROM tasks
            """
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "video_path": row[0],
                "status": row[1],
                "number": row[2],
                "title": row[3],
                "source": row[4],
                "target_dir": row[5],
                "poster_path": row[6],
                "reason": row[7],
                "detail": row[8],
                "updated_at": row[9],
            }
            for row in rows
        ]

    def get_task(self, video_path: str) -> dict[str, str] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT video_path, status, number, title, source, target_dir, poster_path, reason, detail, updated_at
                FROM tasks
                WHERE video_path = ?
                """,
                (video_path,),
            ).fetchone()
        if row is None:
            return None
        return {
            "video_path": row[0],
            "status": row[1],
            "number": row[2],
            "title": row[3],
            "source": row[4],
            "target_dir": row[5],
            "poster_path": row[6],
            "reason": row[7],
            "detail": row[8],
            "updated_at": row[9],
        }

    def summary(self) -> dict[str, int]:
        with self._connection() as conn:
            rows = conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall()
        return {status: count for status, count in rows}

    def dashboard_summary(self) -> dict[str, int]:
        summary = self.summary()
        return {
            "total": sum(summary.values()),
            "success": summary.get("success", 0),
            "failed": summary.get("failed", 0),
            "running": summary.get("running", 0),
        }

    def recent_posters(self, limit: int = 6) -> list[dict[str, str]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT video_path, number, title, source, target_dir, poster_path, updated_at
                FROM tasks
                WHERE status = 'success' AND poster_path != ''
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "video_path": row[0],
                "number": row[1],
                "title": row[2],
                "source": row[3],
                "target_dir": row[4],
                "poster_path": row[5],
                "updated_at": row[6],
            }
            for row in rows
        ]
