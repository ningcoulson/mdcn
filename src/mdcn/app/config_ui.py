"""Lightweight local HTML config UI."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree as ET

from mdcn.app.bootstrap import build_orchestrator
from mdcn.config import AppConfig, PathsConfig, build_config_from_dict, config_to_dict, load_config, save_config
from mdcn.output.naming import build_template_context, preview_folder_name, render_folder_template, sanitize_path_component
from mdcn.scanner.files import iter_video_files
from mdcn.scanner.number_parser import extract_candidates, normalize_number
from mdcn.storage.task_repo import TaskRepository

ASSET_DIR = Path(__file__).parent / "assets"


@dataclass(slots=True)
class ConfigUiRunState:
    running: bool = False
    mode: str = ""
    message: str = "idle"
    last_error: str = ""
    last_stats: dict[str, int] = field(default_factory=lambda: {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0})
    queue_total: int = 0
    processed: int = 0
    current_video: str = ""
    current_label: str = ""
    current_number: str = ""
    current_title: str = ""
    current_source: str = ""
    current_crawler: str = ""
    current_candidate: str = ""
    current_target_dir: str = ""
    current_poster: str = ""
    recent_posters: list[dict[str, str]] = field(default_factory=list)
    activity_log: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "mode": self.mode,
                "message": self.message,
                "last_error": self.last_error,
                "last_stats": dict(self.last_stats),
                "queue_total": self.queue_total,
                "processed": self.processed,
                "remaining": max(self.queue_total - self.processed, 0),
                "current_video": self.current_video,
                "current_label": self.current_label,
                "current_number": self.current_number,
                "current_title": self.current_title,
                "current_source": self.current_source,
                "current_crawler": self.current_crawler,
                "current_candidate": self.current_candidate,
                "current_target_dir": self.current_target_dir,
                "current_poster": self.current_poster,
                "recent_posters": list(self.recent_posters),
                "activity_log": list(self.activity_log),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def start(self, mode: str, *, total: int = 0) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.mode = mode
            self.message = _mode_label(mode) + " is running"
            self.last_error = ""
            self.queue_total = total
            self.processed = 0
            self.current_video = ""
            self.current_label = ""
            self.current_number = ""
            self.current_title = ""
            self.current_source = ""
            self.current_crawler = ""
            self.current_candidate = ""
            self.current_target_dir = ""
            self.current_poster = ""
            self.recent_posters = []
            self.activity_log = [f"[{_timestamp()}] {_mode_label(mode)} queued"]
            self.started_at = _timestamp()
            self.finished_at = ""
            return True

    def finish(self, mode: str, stats: dict[str, int]) -> None:
        with self._lock:
            self.running = False
            self.mode = mode
            self.message = _mode_label(mode) + " finished"
            self.last_error = ""
            self.last_stats = dict(stats)
            self.processed = stats.get("succeeded", 0) + stats.get("failed", 0) + stats.get("skipped", 0)
            self._append_log(f"{_mode_label(mode)} finished: scanned={stats.get('scanned', 0)} succeeded={stats.get('succeeded', 0)} failed={stats.get('failed', 0)} skipped={stats.get('skipped', 0)}")
            self.finished_at = _timestamp()

    def fail(self, mode: str, error: str) -> None:
        with self._lock:
            self.running = False
            self.mode = mode
            self.message = _mode_label(mode) + " failed"
            self.last_error = error
            self._append_log(f"{_mode_label(mode)} failed: {error}")
            self.finished_at = _timestamp()

    def update(self, payload: dict[str, Any]) -> None:
        with self._lock:
            event = str(payload.get("event", ""))
            stats = payload.get("stats")
            if isinstance(stats, dict):
                self.last_stats = {
                    "scanned": int(stats.get("scanned", self.last_stats["scanned"])),
                    "succeeded": int(stats.get("succeeded", self.last_stats["succeeded"])),
                    "failed": int(stats.get("failed", self.last_stats["failed"])),
                    "skipped": int(stats.get("skipped", self.last_stats["skipped"])),
                }
                self.processed = self.last_stats["succeeded"] + self.last_stats["failed"] + self.last_stats["skipped"]
            if "total" in payload:
                self.queue_total = int(payload.get("total") or 0)
            if event == "video_started":
                self.current_video = str(payload.get("video_path", ""))
                self.current_label = str(payload.get("label") or Path(self.current_video).name)
                self.current_number = ""
                self.current_title = ""
                self.current_source = ""
                self.current_crawler = ""
                self.current_candidate = ""
                self.current_target_dir = ""
                self.current_poster = ""
                self.message = f"{_mode_label(self.mode)} is running"
                self._append_log(f"Start video: {self.current_label}")
            elif event == "candidate_try":
                crawler = str(payload.get("crawler", ""))
                candidate = str(payload.get("candidate", ""))
                self.current_crawler = crawler
                self.current_candidate = candidate
                self._append_log(f"Checking {crawler} for {candidate}")
            elif event == "candidate_miss":
                crawler = str(payload.get("crawler", ""))
                candidate = str(payload.get("candidate", ""))
                error_name = str(payload.get("error_type", "error"))
                self._append_log(f"Miss on {crawler} for {candidate} ({error_name})")
            elif event == "video_succeeded":
                self.current_video = str(payload.get("video_path", self.current_video))
                self.current_number = str(payload.get("number", ""))
                self.current_title = str(payload.get("title", ""))
                self.current_source = str(payload.get("source", ""))
                self.current_crawler = self.current_source or self.current_crawler
                self.current_candidate = self.current_number or self.current_candidate
                self.current_target_dir = str(payload.get("target_dir", ""))
                self.current_poster = str(payload.get("poster_path", ""))
                self._append_log(
                    f"Matched {self.current_source or 'site'}: {(self.current_number or '').strip()} {(self.current_title or '').strip()}".strip()
                )
                if self.current_poster:
                    poster_entry = {
                        "poster_path": self.current_poster,
                        "number": self.current_number,
                        "title": self.current_title,
                        "source": self.current_source,
                        "target_dir": self.current_target_dir,
                        "video_path": self.current_video,
                    }
                    self.recent_posters = [poster_entry, *[item for item in self.recent_posters if item.get("poster_path") != self.current_poster]][:6]
            elif event == "run_finished":
                self.message = _mode_label(self.mode) + " finished"

    def _append_log(self, text: str) -> None:
        entry = f"[{_timestamp()}] {text}"
        self.activity_log = [*self.activity_log[-79:], entry]


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _mode_label(mode: str) -> str:
    if mode == "retry_failed":
        return "Retry failed"
    if mode == "retry_selected":
        return "Retry selected"
    return "Scrape"


def _task_repo_path(config: AppConfig) -> Path:
    return config.paths.target_root / ".mdcn" / "tasks.db"


def _load_task_snapshot(config_path: Path, *, status: str = "all", query: str = "") -> dict[str, Any]:
    try:
        config = load_config(config_path)
    except Exception as exc:  # noqa: BLE001
        return {"summary": {}, "recent": [], "error": str(exc)}

    db_path = _task_repo_path(config)
    if not db_path.exists():
        return {"summary": {}, "recent": []}

    repo = TaskRepository(db_path)
    return {
        "summary": repo.summary(),
        "recent": repo.list_recent_tasks(limit=20, status=status, query=query or None),
    }


def _poster_url(path: str) -> str:
    if not path:
        return ""
    return f"/media?path={path}"


def _load_file_snapshot(config_path: Path) -> dict[str, Any]:
    try:
        config = load_config(config_path)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    source_dir = config.paths.source_dir
    target_root = config.paths.target_root
    source_files = []
    if source_dir.exists() and source_dir.is_dir():
        source_files = iter_video_files(source_dir, config.scanner.normalized_extensions())

    library_dirs = 0
    if target_root.exists() and target_root.is_dir():
        library_dirs = sum(1 for child in target_root.iterdir() if child.is_dir() and child.name != ".mdcn")

    return {
        "source_dir": str(source_dir),
        "target_root": str(target_root),
        "source_exists": source_dir.exists() and source_dir.is_dir(),
        "target_exists": target_root.exists() and target_root.is_dir(),
        "source_pending": len(source_files),
        "library_folders": library_dirs,
        "config_parent": str(config_path.parent),
    }


def _load_dashboard_snapshot(config_path: Path, run_state: ConfigUiRunState) -> dict[str, Any]:
    tasks = _load_task_snapshot(config_path)
    files = _load_file_snapshot(config_path)
    recent_posters = []
    try:
        config = load_config(config_path)
        repo = TaskRepository(_task_repo_path(config))
        recent_posters = repo.recent_posters(limit=8)
    except Exception:  # noqa: BLE001
        recent_posters = []

    for item in recent_posters:
        item["poster_url"] = _poster_url(item.get("poster_path", ""))

    state = run_state.snapshot()
    if state.get("current_poster"):
        state["current_poster_url"] = _poster_url(str(state["current_poster"]))
    else:
        state["current_poster_url"] = ""

    summary = tasks.get("summary", {})
    dashboard_totals = {
        "total": int(summary.get("success", 0)) + int(summary.get("failed", 0)) + int(summary.get("running", 0)),
        "success": int(summary.get("success", 0)),
        "failed": int(summary.get("failed", 0)),
        "running": int(summary.get("running", 0)),
    }
    if state["queue_total"]:
        dashboard_totals["total"] = state["queue_total"]

    return {
        "run": state,
        "tasks": tasks,
        "files": files,
        "totals": dashboard_totals,
        "recent_posters": recent_posters,
    }


def _is_safe_media_path(path: Path, *roots: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        return False
    for root in roots:
        try:
            root_resolved = root.resolve(strict=False)
            resolved.relative_to(root_resolved)
            return True
        except ValueError:
            continue
    return False


def _open_path_in_system(path: str) -> bool:
    target = Path(path).expanduser()
    if not target.exists():
        return False
    system = platform.system()
    try:
        if system == "Darwin":
            return subprocess.run(["open", str(target)], check=False, capture_output=True, text=True).returncode == 0
        if system == "Windows":
            os.startfile(str(target))  # type: ignore[attr-defined]
            return True
        for command in (["xdg-open", str(target)], ["gio", "open", str(target)]):
            if subprocess.run(command, check=False, capture_output=True, text=True).returncode == 0:
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".ts", ".mov", ".wmv", ".flv", ".m4v", ".webm"}
_POSTER_CANDIDATE_RE = re.compile(r"(?i)^(poster|.+_poster(?:_\d+)?)\.(jpg|jpeg|png|webp)$")


def _iter_leaf_media_folders(base_dir: Path, *, recursive: bool) -> list[tuple[Path, list[Path]]]:
    if not recursive:
        videos = [item for item in base_dir.iterdir() if item.is_file() and item.suffix.lower() in _VIDEO_EXTENSIONS]
        return [(base_dir, videos)] if videos else []

    leaves: list[tuple[Path, list[Path]]] = []
    for dir_path, dir_names, file_names in os.walk(base_dir):
        current = Path(dir_path)
        if current.name == ".mdcn":
            dir_names[:] = []
            continue
        videos = [current / name for name in file_names if Path(name).suffix.lower() in _VIDEO_EXTENSIONS]
        if videos:
            leaves.append((current, videos))
    return leaves


def _extract_number_title_from_folder(folder: Path, videos: list[Path]) -> tuple[str, str]:
    number, title = _extract_from_metadata_json(folder)
    if not number or not title:
        nfo_number, nfo_title = _extract_from_nfo(folder)
        number = number or nfo_number
        title = title or nfo_title

    if not number or not title:
        folder_number, folder_title = _extract_from_folder_name(folder.name)
        number = number or folder_number
        title = title or folder_title

    if not number:
        video_number, video_title = _extract_from_video_name(videos)
        number = number or video_number
        title = title or video_title

    return normalize_number(number or ""), sanitize_path_component(title or "")


def _extract_from_metadata_json(folder: Path) -> tuple[str, str]:
    metadata_path = folder / "metadata.json"
    if not metadata_path.exists():
        return "", ""
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return "", ""
    number = normalize_number(str(data.get("number") or data.get("id") or ""))
    title = sanitize_path_component(str(data.get("title") or data.get("originaltitle") or ""))
    return number, title


def _extract_from_nfo(folder: Path) -> tuple[str, str]:
    for nfo in sorted(folder.glob("*.nfo")):
        try:
            root = ET.fromstring(nfo.read_text(encoding="utf-8", errors="ignore"))
        except Exception:  # noqa: BLE001
            continue
        number = normalize_number((root.findtext("id") or root.findtext("num") or root.findtext("sorttitle") or "").strip())
        title = sanitize_path_component((root.findtext("title") or root.findtext("originaltitle") or "").strip())
        if number or title:
            return number, title
    return "", ""


def _extract_from_folder_name(name: str) -> tuple[str, str]:
    match = re.match(r"(?i)^([A-Za-z0-9]+(?:-[A-Za-z0-9]+)?)\s+(.+)$", name.strip())
    if not match:
        return "", ""
    return normalize_number(match.group(1)), sanitize_path_component(match.group(2))


def _extract_from_video_name(videos: list[Path]) -> tuple[str, str]:
    for video in sorted(videos, key=lambda path: path.stat().st_size, reverse=True):
        candidates = extract_candidates(video.stem)
        if not candidates:
            continue
        number = candidates[0].normalized
        title = sanitize_path_component(video.stem.replace(candidates[0].raw, "").strip(" -_[]【】."))
        return normalize_number(number), title
    return "", ""


def _render_name_rule(rule: str, *, context: dict[str, str], fallback: str) -> str:
    rendered = render_folder_template(rule.strip() or fallback, context)
    leaf = rendered.split("/")[-1] if rendered else ""
    clean = sanitize_path_component(leaf)
    return clean or fallback


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def organize_files_in_directory(
    *,
    base_dir: Path,
    folder_rule: str,
    video_rule: str,
    poster_rule: str,
    recursive: bool,
    apply_changes: bool,
) -> dict[str, Any]:
    if not base_dir.exists() or not base_dir.is_dir():
        return {"ok": False, "error": "目录不存在或不是文件夹。"}

    folders = _iter_leaf_media_folders(base_dir, recursive=recursive)
    summary = {
        "folders_scanned": len(folders),
        "folders_updated": 0,
        "videos_renamed": 0,
        "posters_renamed": 0,
        "posters_deleted": 0,
        "nfo_renamed": 0,
        "nfo_deleted": 0,
        "skipped_no_number": 0,
        "skipped_no_title": 0,
    }
    details: list[dict[str, Any]] = []

    for folder, videos in folders:
        number, title = _extract_number_title_from_folder(folder, videos)
        if not number:
            summary["skipped_no_number"] += 1
            continue
        if not title:
            summary["skipped_no_title"] += 1
            continue

        context = build_template_context(number=number, title=title)
        folder_name = _render_name_rule(folder_rule, context=context, fallback=f"{number} {title}")
        video_base = _render_name_rule(video_rule, context=context, fallback=number)
        poster_name = _render_name_rule(poster_rule, context=context, fallback=f"{number}_poster.jpg")
        if "." not in poster_name:
            poster_name += ".jpg"
        canonical_poster = folder / poster_name

        folder_actions: list[str] = []
        ordered_videos = sorted(videos, key=lambda path: path.stat().st_size, reverse=True)
        for index, video in enumerate(ordered_videos, start=1):
            base = video_base if index == 1 else f"{video_base}_part{index}"
            target_name = f"{base}{video.suffix.lower()}"
            target = folder / target_name
            if video.name == target_name:
                continue
            folder_actions.append(f"video: {video.name} -> {target_name}")
            summary["videos_renamed"] += 1
            if apply_changes:
                video.rename(_unique_path(target))

        poster_candidates = [item for item in folder.iterdir() if item.is_file() and _POSTER_CANDIDATE_RE.match(item.name)]
        if poster_candidates:
            selected = None
            for item in poster_candidates:
                if item.name.lower() == canonical_poster.name.lower():
                    selected = item
                    break
            if selected is None:
                selected = max(poster_candidates, key=lambda path: path.stat().st_size)

            if selected.name != canonical_poster.name:
                folder_actions.append(f"poster: {selected.name} -> {canonical_poster.name}")
                summary["posters_renamed"] += 1
                if apply_changes:
                    if canonical_poster.exists():
                        canonical_poster.unlink()
                    if selected.suffix.lower() in {".jpg", ".jpeg"}:
                        selected.rename(canonical_poster)
                    else:
                        shutil.copy2(selected, canonical_poster)
                        selected.unlink(missing_ok=True)

            for item in poster_candidates:
                if item.name == canonical_poster.name:
                    continue
                folder_actions.append(f"poster delete: {item.name}")
                summary["posters_deleted"] += 1
                if apply_changes:
                    item.unlink(missing_ok=True)

        nfo_files = sorted(folder.glob("*.nfo"))
        if nfo_files:
            desired_nfo = folder / f"{number}.nfo"
            keeper = None
            for nfo in nfo_files:
                if nfo.name.lower() == desired_nfo.name.lower():
                    keeper = nfo
                    break
            if keeper is None:
                keeper = nfo_files[0]
                folder_actions.append(f"nfo: {keeper.name} -> {desired_nfo.name}")
                summary["nfo_renamed"] += 1
                if apply_changes:
                    if desired_nfo.exists():
                        desired_nfo.unlink()
                    keeper.rename(desired_nfo)
                keeper = desired_nfo
            for nfo in nfo_files:
                if keeper is not None and nfo.name == keeper.name:
                    continue
                folder_actions.append(f"nfo delete: {nfo.name}")
                summary["nfo_deleted"] += 1
                if apply_changes:
                    nfo.unlink(missing_ok=True)

        if folder.name != folder_name:
            summary["folders_updated"] += 1
            folder_actions.append(f"folder: {folder.name} -> {folder_name}")
            if apply_changes:
                folder.rename(_unique_path(folder.with_name(folder_name)))

        if folder_actions:
            details.append(
                {
                    "folder": str(folder),
                    "number": number,
                    "title": title,
                    "actions": folder_actions,
                }
            )

    return {
        "ok": True,
        "applied": apply_changes,
        "base_dir": str(base_dir),
        "summary": summary,
        "details": details[:120],
        "details_total": len(details),
    }


def _start_background_run(
    run_state: ConfigUiRunState,
    config_path: Path,
    mode: str,
    *,
    video_paths: list[str] | None = None,
) -> bool:
    def worker() -> None:
        try:
            config = load_config(config_path)
            if mode == "retry_failed":
                repo = TaskRepository(_task_repo_path(config))
                retry_paths = repo.list_failed_video_paths()
                if not run_state.start(mode, total=len(retry_paths)):
                    return
                orchestrator = build_orchestrator(config, progress_callback=run_state.update)
                stats = asyncio.run(orchestrator.retry_video_paths(retry_paths))
            elif mode == "retry_selected":
                selected_paths = video_paths or []
                if not run_state.start(mode, total=len(selected_paths)):
                    return
                orchestrator = build_orchestrator(config, progress_callback=run_state.update)
                stats = asyncio.run(orchestrator.retry_video_paths(selected_paths))
            else:
                files = iter_video_files(config.paths.source_dir, config.scanner.normalized_extensions())
                if not run_state.start(mode, total=len(files)):
                    return
                orchestrator = build_orchestrator(config, progress_callback=run_state.update)
                stats = asyncio.run(orchestrator.run(files))
            run_state.finish(
                mode,
                {
                    "scanned": stats.scanned,
                    "succeeded": stats.succeeded,
                    "failed": stats.failed,
                    "skipped": stats.skipped,
                },
            )
        except Exception as exc:  # noqa: BLE001
            run_state.fail(mode, str(exc))

    if run_state.running:
        return False
    thread = threading.Thread(target=worker, name=f"mdcn-{mode}", daemon=True)
    thread.start()
    return True


def serve_config_ui(
    *,
    config_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> ThreadingHTTPServer:
    config_file = Path(config_path)
    server = _build_server(config_file, host, port)
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(1.0, _open_browser_url, args=(url,)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return server


def _open_browser_url(url: str) -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            completed = subprocess.run(["open", url], check=False, capture_output=True, text=True)
            if completed.returncode == 0:
                return True
        elif system == "Windows":
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        else:
            for command in (["xdg-open", url], ["gio", "open", url]):
                completed = subprocess.run(command, check=False, capture_output=True, text=True)
                if completed.returncode == 0:
                    return True
    except Exception:  # noqa: BLE001
        pass
    try:
        return webbrowser.open(url, new=1, autoraise=True)
    except Exception:  # noqa: BLE001
        return False


def _build_server(config_path: Path, host: str, port: int) -> ThreadingHTTPServer:
    handler = _make_handler(config_path, ConfigUiRunState())
    return ThreadingHTTPServer((host, port), handler)


def _make_handler(config_path: Path, run_state: ConfigUiRunState):
    class ConfigUIHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                self._send_html(render_config_ui_html())
                return
            if parsed.path.startswith("/assets/"):
                asset_name = parsed.path.removeprefix("/assets/").strip("/")
                asset_path = (ASSET_DIR / asset_name).resolve()
                if not asset_path.exists() or ASSET_DIR.resolve() not in asset_path.parents:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                    return
                body = asset_path.read_bytes()
                content_type = mimetypes.guess_type(str(asset_path))[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/dashboard":
                self._send_json(_load_dashboard_snapshot(config_path, run_state))
                return
            if parsed.path == "/api/config":
                _ensure_config_exists(config_path)
                config = load_config(config_path)
                payload = config_to_dict(config)
                payload["config_path"] = str(config_path)
                self._send_json(payload)
                return
            if parsed.path == "/api/files":
                self._send_json(_load_file_snapshot(config_path))
                return
            if parsed.path == "/api/preview":
                query = parse_qs(parsed.query)
                template = query.get("template", ["{number} {title}"])[0]
                self._send_json({"preview": preview_folder_name(template)})
                return
            if parsed.path == "/api/run-status":
                self._send_json(run_state.snapshot())
                return
            if parsed.path == "/api/validate-paths":
                query = parse_qs(parsed.query)
                source_dir = query.get("source_dir", [""])[0]
                target_root = query.get("target_root", [""])[0]
                self._send_json(validate_path_settings(source_dir, target_root))
                return
            if parsed.path == "/api/tasks":
                query = parse_qs(parsed.query)
                status = query.get("status", ["all"])[0]
                text_query = query.get("query", [""])[0]
                self._send_json(_load_task_snapshot(config_path, status=status, query=text_query))
                return
            if parsed.path == "/api/task":
                query = parse_qs(parsed.query)
                video_path = query.get("video_path", [""])[0]
                try:
                    config = load_config(config_path)
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                repo = TaskRepository(_task_repo_path(config))
                task = repo.get_task(video_path)
                if task is None:
                    self._send_json({"ok": False, "error": "Task not found."}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True, "task": task})
                return
            if parsed.path == "/media":
                query = parse_qs(parsed.query)
                raw_path = unquote(query.get("path", [""])[0]).strip()
                if not raw_path:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Missing path")
                    return
                try:
                    config = load_config(config_path)
                except Exception:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid config")
                    return
                media_path = Path(raw_path).expanduser()
                if not _is_safe_media_path(media_path, config.paths.target_root, config_path.parent):
                    self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                    return
                body = media_path.read_bytes()
                content_type = mimetypes.guess_type(str(media_path))[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in (
                "/api/config",
                "/api/run",
                "/api/tasks/retry",
                "/api/pick-directory",
                "/api/open-path",
                "/api/files/organize",
            ):
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw_body)
            if self.path == "/api/pick-directory":
                initial_path = str(payload.get("initial_path", "")).strip()
                selected = pick_directory(initial_path)
                if selected:
                    self._send_json({"ok": True, "selected_path": selected})
                else:
                    self._send_json(
                        {
                            "ok": False,
                            "selected_path": "",
                            "error": "目录选择器没有成功返回路径。请确认当前输入路径有效，或直接手动输入目录。",
                        },
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            if self.path == "/api/open-path":
                target_path = str(payload.get("path", "")).strip()
                opened = _open_path_in_system(target_path)
                self._send_json({"ok": opened})
                return
            if self.path == "/api/files/organize":
                target_dir = Path(str(payload.get("directory", "")).strip()).expanduser()
                folder_rule = str(payload.get("folder_rule", "{number} {title}")).strip() or "{number} {title}"
                video_rule = str(payload.get("video_rule", "{number}")).strip() or "{number}"
                poster_rule = str(payload.get("poster_rule", "{number}_poster.jpg")).strip() or "{number}_poster.jpg"
                recursive = bool(payload.get("recursive", True))
                apply_changes = bool(payload.get("apply", False))
                result = organize_files_in_directory(
                    base_dir=target_dir,
                    folder_rule=folder_rule,
                    video_rule=video_rule,
                    poster_rule=poster_rule,
                    recursive=recursive,
                    apply_changes=apply_changes,
                )
                if result.get("ok"):
                    self._send_json(result)
                else:
                    self._send_json(result, status=HTTPStatus.BAD_REQUEST)
                return
            if self.path == "/api/tasks/retry":
                video_path = str(payload.get("video_path", "")).strip()
                started = _start_background_run(run_state, config_path, "retry_selected", video_paths=[video_path] if video_path else [])
                if started:
                    self._send_json({"ok": True, "started": True, "status": run_state.snapshot()})
                    return
                self._send_json(
                    {"ok": False, "started": False, "error": "A run is already in progress.", "status": run_state.snapshot()},
                    status=HTTPStatus.CONFLICT,
                )
                return

            config = build_config_from_ui_payload(payload)
            save_config(config, config_path)

            if self.path == "/api/config":
                self._send_json({"ok": True, "config_path": str(config_path)})
                return

            mode = str(payload.get("mode", "scrape")).strip() or "scrape"
            started = _start_background_run(run_state, config_path, mode)
            if started:
                self._send_json({"ok": True, "started": True, "mode": mode, "status": run_state.snapshot()})
                return
            self._send_json(
                {"ok": False, "started": False, "error": "A run is already in progress.", "status": run_state.snapshot()},
                status=HTTPStatus.CONFLICT,
            )

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_html(self, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ConfigUIHandler


def build_config_from_ui_payload(payload: dict[str, Any]):
    clean = {
        "source": {"dir": str(payload.get("source_dir", "")).strip()},
        "target": {"root": str(payload.get("target_root", "")).strip()},
        "output": {
            "max_images": int(payload.get("max_images", 6)),
            "write_nfo": bool(payload.get("write_nfo", True)),
            "write_json": bool(payload.get("write_json", True)),
            "folder_template": str(payload.get("folder_template", "{number} {title}")).strip(),
        },
        "network": {
            "proxy": str(payload.get("proxy", "")).strip(),
            "timeout": float(payload.get("timeout", 20.0)),
            "retries": int(payload.get("retries", 2)),
        },
        "scanner": {
            "extensions": [item.strip() for item in str(payload.get("extensions", "")).split(",") if item.strip()],
        },
        "priority": {
            "site_order": [item.strip() for item in str(payload.get("site_order", "")).split(",") if item.strip()],
        },
        "sites": {
            "madouqu": {
                "enabled": bool(payload.get("site_madouqu_enabled", True)),
                "base_url": str(payload.get("site_madouqu_base_url", "")).strip(),
                "mirrors": [item.strip() for item in str(payload.get("site_madouqu_mirrors", "")).split(",") if item.strip()],
            },
            "mdtv": {
                "enabled": bool(payload.get("site_mdtv_enabled", True)),
                "base_url": str(payload.get("site_mdtv_base_url", "")).strip(),
                "mirrors": [item.strip() for item in str(payload.get("site_mdtv_mirrors", "")).split(",") if item.strip()],
            },
            "madouclub": {
                "enabled": bool(payload.get("site_madouclub_enabled", True)),
                "base_url": str(payload.get("site_madouclub_base_url", "")).strip(),
                "mirrors": [item.strip() for item in str(payload.get("site_madouclub_mirrors", "")).split(",") if item.strip()],
            },
            "avjia": {
                "enabled": bool(payload.get("site_avjia_enabled", True)),
                "base_url": str(payload.get("site_avjia_base_url", "")).strip(),
                "mirrors": [item.strip() for item in str(payload.get("site_avjia_mirrors", "")).split(",") if item.strip()],
            },
            "tianmei": {
                "enabled": bool(payload.get("site_tianmei_enabled", True)),
                "base_url": str(payload.get("site_tianmei_base_url", "")).strip(),
                "mirrors": [item.strip() for item in str(payload.get("site_tianmei_mirrors", "")).split(",") if item.strip()],
            },
        },
    }
    return build_config_from_dict(clean)


def _ensure_config_exists(config_path: Path) -> None:
    if config_path.exists():
        return
    default_config = AppConfig(
        paths=PathsConfig(
            source_dir=Path("/path/to/failed"),
            target_root=Path("/path/to/library"),
        )
    )
    save_config(default_config, config_path)


def validate_path_settings(source_dir: str, target_root: str) -> dict[str, Any]:
    source_path = Path(source_dir).expanduser() if source_dir.strip() else None
    target_path = Path(target_root).expanduser() if target_root.strip() else None

    source_ready = False
    target_ready = False
    source_message = ""
    target_message = ""

    if source_path is None:
        source_message = "请先填写源目录。"
    elif source_path.exists() and source_path.is_dir():
        source_ready = True
        source_message = "源目录存在，可以开始扫描。"
    elif source_path.exists():
        source_message = "源目录存在，但它不是文件夹。"
    else:
        source_message = "源目录不存在，请检查路径。"

    if target_path is None:
        target_message = "请先填写目标目录。"
    elif target_path.exists() and target_path.is_dir():
        if os.access(target_path, os.W_OK):
            target_ready = True
            target_message = "目标目录存在，且当前可写。"
        else:
            target_message = "目标目录存在，但当前没有写入权限。"
    elif target_path.exists():
        target_message = "目标目录存在，但它不是文件夹。"
    else:
        parent = target_path.parent
        while parent != parent.parent and not parent.exists():
            parent = parent.parent
        if parent.exists() and parent.is_dir() and os.access(parent, os.W_OK):
            target_ready = True
            target_message = f"目标目录尚不存在，但可以在 {parent} 下创建。"
        else:
            target_message = "目标目录不存在，且父目录不可写或无效。"

    return {
        "source_ready": source_ready,
        "target_ready": target_ready,
        "can_run": source_ready and target_ready,
        "source_message": source_message,
        "target_message": target_message,
    }


def pick_directory(initial_path: str = "") -> str | None:
    system = platform.system()
    path = initial_path.strip()
    if system == "Darwin":
        return _pick_directory_macos(path)
    if system == "Windows":
        return _pick_directory_windows(path)
    return _pick_directory_linux(path)


def _pick_directory_macos(initial_path: str) -> str | None:
    script_lines = []
    initial_dir = Path(initial_path).expanduser() if initial_path else None
    if initial_dir and initial_dir.exists() and initial_dir.is_dir():
        script_lines.append(
            f'set chosenFolder to choose folder with prompt "Select a folder for mdcn" default location POSIX file "{initial_path}"'
        )
    else:
        script_lines.append('set chosenFolder to choose folder with prompt "Select a folder for mdcn"')
    script_lines.append("POSIX path of chosenFolder")
    try:
        result = subprocess.run(
            ["osascript", *sum([["-e", line] for line in script_lines], [])],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None
    selected = result.stdout.strip()
    return selected or None


def _pick_directory_windows(initial_path: str) -> str | None:
    start_path = initial_path.replace("'", "''")
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Select a folder for mdcn'
if ('{start_path}') {{ $dialog.SelectedPath = '{start_path}' }}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  Write-Output $dialog.SelectedPath
}}
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None
    selected = result.stdout.strip()
    return selected or None


def _pick_directory_linux(initial_path: str) -> str | None:
    commands: list[list[str]] = []
    if initial_path:
        commands.append(["zenity", "--file-selection", "--directory", f"--filename={initial_path}/"])
        commands.append(["kdialog", "--getexistingdirectory", initial_path])
    else:
        commands.append(["zenity", "--file-selection", "--directory"])
        commands.append(["kdialog", "--getexistingdirectory", os.path.expanduser("~")])

    for command in commands:
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        selected = result.stdout.strip()
        if selected:
            return selected
    return None


def render_config_ui_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>mdcn Config Studio</title>
  <style>
    :root {
      --bg: #0f141b;
      --panel: rgba(172, 176, 180, 0.12);
      --panel-strong: rgba(150, 154, 160, 0.20);
      --ink: #eef3fa;
      --muted: rgba(245, 248, 252, 0.72);
      --line: rgba(255, 255, 255, 0.18);
      --accent: #8ec5ff;
      --accent-deep: #589dff;
      --olive: #8cb8a0;
      --gold: #f0c58d;
      --ok: #77e2ad;
      --danger: #ff9086;
      --shadow: 0 30px 80px rgba(6, 12, 20, 0.46);
      --soft-shadow: 0 16px 40px rgba(6, 12, 20, 0.22);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI Variable", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background: #0b0e12;
      min-height: 100vh;
      overflow-x: hidden;
      position: relative;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background:
        radial-gradient(circle at 50% 18%, rgba(255,255,255,0.04), transparent 0 34%),
        linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0));
      pointer-events: none;
    }
    .scene {
      position: relative;
      min-height: 100vh;
      padding: 24px;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .scene::before {
      content: "";
      position: absolute;
      inset: -6%;
      background:
        linear-gradient(180deg, rgba(6,10,14,0.12), rgba(7,11,15,0.20)),
        url("/assets/rain-scene-alt.jpg") center center / cover no-repeat;
      filter: blur(14px) saturate(0.78) brightness(0.50);
      transform: scale(1.07);
      transform-origin: center;
    }
    .scene::after {
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 50% 46%, rgba(255,255,255,0.05), transparent 0 28%),
        linear-gradient(180deg, rgba(5,8,12,0.18), rgba(6,10,14,0.38));
      pointer-events: none;
    }
    .rain-canvas {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
      pointer-events: none;
      opacity: 0.58;
      filter: saturate(1.0) contrast(1.02);
      z-index: 1;
    }
    .rain-layer,
    .rain-layer::before,
    .rain-layer::after {
      position: absolute;
      inset: 0;
      pointer-events: none;
      content: "";
    }
    .rain-layer.hidden {
      display: none;
    }
    .rain-layer {
      background-image: linear-gradient(transparent 0%, rgba(255,255,255,0.04) 48%, transparent 100%);
      opacity: 0.12;
      filter: blur(0.2px);
      animation: rain-drift 9s linear infinite;
      z-index: 1;
    }
    .rain-layer::before {
      background-image: repeating-linear-gradient(
        102deg,
        rgba(255,255,255,0.00) 0px,
        rgba(255,255,255,0.00) 14px,
        rgba(255,255,255,0.18) 15px,
        rgba(255,255,255,0.00) 18px
      );
      background-size: 260px 260px;
      opacity: 0.28;
      animation: rain-fall 1.35s linear infinite;
    }
    .rain-layer::after {
      background-image: repeating-linear-gradient(
        104deg,
        rgba(255,255,255,0.00) 0px,
        rgba(255,255,255,0.00) 22px,
        rgba(183, 214, 255, 0.14) 23px,
        rgba(255,255,255,0.00) 26px
      );
      background-size: 340px 340px;
      opacity: 0.18;
      animation: rain-fall 1.9s linear infinite reverse;
    }
    .window-shell {
      position: relative;
      z-index: 2;
      width: min(68vw, 1120px, calc(100vw - 120px), calc((100vh - 48px) * 1.7778));
      aspect-ratio: 16 / 9;
      height: auto;
      max-height: calc(100vh - 48px);
      border-radius: 0;
      background: transparent;
      border: none;
      box-shadow: none;
      backdrop-filter: none;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    .window-topbar {
      display: none;
    }
    .window-title {
      color: transparent;
      font-size: 0;
    }
    .app {
      width: 100%;
      margin: 0 auto;
      display: grid;
      grid-template-columns: 1fr;
      gap: 0;
      padding: 0;
      flex: 1;
      min-height: 0;
      height: 100%;
    }
    .sidebar, .surface {
      background: var(--panel);
      border: none;
      border-radius: 18px;
      box-shadow: none;
      backdrop-filter: blur(22px);
    }
    .sidebar { display: none; }
    .eyebrow {
      font-size: 11px;
      letter-spacing: 0.24em;
      text-transform: uppercase;
      color: var(--accent-deep);
      font-weight: 700;
      margin-bottom: 12px;
    }
    .brand-title {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 52px;
      line-height: 0.92;
      letter-spacing: -0.04em;
    }
    .brand-copy {
      margin: 14px 0 18px;
      color: var(--muted);
      line-height: 1.8;
      font-size: 15px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.06);
      border: 1px solid var(--line);
      color: #d8e5f6;
      font-size: 13px;
      font-weight: 700;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .welcome-card, .soft-card {
      margin-top: 18px;
      padding: 16px;
      border-radius: 22px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.04);
      box-shadow: var(--soft-shadow);
    }
    .soft-card p, .welcome-body, .welcome-alert {
      margin: 0;
      color: var(--muted);
      line-height: 1.75;
      white-space: pre-line;
      font-size: 14px;
    }
    .welcome-title, .mini-title {
      margin: 0 0 10px;
      color: var(--gold);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }
    .welcome-alert { margin-top: 10px; color: var(--accent-deep); font-weight: 700; }
    .module-nav {
      margin-top: 18px;
      display: grid;
      gap: 8px;
    }
    .nav-button {
      width: 100%;
      text-align: left;
      border: 1px solid transparent;
      border-radius: 20px;
      padding: 12px 14px;
      background: rgba(255,255,255,0.04);
      color: var(--muted);
      cursor: pointer;
      font: inherit;
      transition: 0.18s ease;
    }
    .nav-inner {
      display: grid;
      grid-template-columns: 28px 1fr;
      gap: 12px;
      align-items: start;
    }
    .nav-icon {
      width: 28px;
      height: 28px;
      border-radius: 12px;
      background: rgba(255,255,255,0.07);
      border: 1px solid rgba(255,255,255,0.08);
      position: relative;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
    }
    .nav-icon::before {
      content: "";
      position: absolute;
      inset: 7px;
      border-radius: 8px;
      background: linear-gradient(135deg, rgba(142,197,255,0.95), rgba(240,197,141,0.68));
      opacity: 0.82;
    }
    .nav-button strong {
      display: block;
      margin-bottom: 4px;
      color: #f4f8ff;
      font-size: 15px;
    }
    .nav-button span {
      font-size: 13px;
      line-height: 1.5;
    }
    .nav-button.active {
      background: linear-gradient(135deg, rgba(142,197,255,0.14), rgba(255,255,255,0.08));
      border-color: rgba(142,197,255,0.18);
      transform: translateX(4px);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 16px 34px rgba(6,12,20,0.22);
    }
    .surface {
      padding: 8px 10px 92px;
      min-height: 0;
      height: 100%;
      max-height: 100%;
      overflow: auto;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.015)),
        var(--panel);
    }
    .topbar {
      display: none;
    }
    .title {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 40px;
      letter-spacing: -0.04em;
      color: #f5f8fd;
    }
    .subtitle {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.75;
      max-width: 560px;
    }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .topbar-actions {
      display: none;
    }
    .hidden-controls {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    button {
      border: 1px solid transparent;
      border-radius: 999px;
      padding: 12px 18px;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
      box-shadow: var(--soft-shadow);
      transition: 0.18s ease;
    }
    button:hover { transform: translateY(-2px); }
    button.primary { background: linear-gradient(135deg, var(--accent), var(--accent-deep)); color: #09131c; }
    button.secondary { background: rgba(255,255,255,0.08); color: #dbeaff; border-color: var(--line); }
    #runButtonHome,
    #retryFailedButtonHome {
      padding: 9px 14px;
      font-size: 11px;
      box-shadow: none;
    }
    .view { display: none; }
    .view.active { display: block; }
    .grid-4, .grid-3, .grid-2 {
      display: grid;
      gap: 16px;
    }
    .grid-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .metric, .panel-card, .hero-card, .task-item, .poster-item {
      background: rgba(255,255,255,0.05);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--soft-shadow);
    }
    .metric { padding: 14px; }
    .metric-label {
      color: var(--gold);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      margin-bottom: 6px;
    }
    .metric-value {
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 30px;
      letter-spacing: -0.05em;
    }
    .metric-sub {
      margin-top: 4px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.6;
    }
    .stat-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-top: 2px;
      padding: 2px 0;
      border-radius: 0;
      background: transparent;
      border: none;
    }
    .stat-pill {
      padding: 0;
      border-radius: 0;
      background: transparent;
      border: none;
      position: relative;
      display: inline-flex;
      align-items: baseline;
      gap: 5px;
    }
    .stat-pill:not(:last-child)::after {
      content: "·";
      position: static;
      width: auto;
      background: transparent;
      color: rgba(255,255,255,0.22);
      margin-left: 6px;
    }
    .stat-pill strong {
      display: inline;
      color: rgba(244,248,255,0.88);
      font-size: 12px;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      letter-spacing: -0.04em;
      margin-top: 0;
    }
    .stat-pill span {
      color: rgba(216,220,227,0.58);
      font-size: 8px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      font-weight: 800;
    }
    .hero-card {
      padding: 0;
      display: grid;
      grid-template-columns: 1.08fr 0.92fr;
      gap: 14px;
      margin-bottom: 8px;
      background: transparent;
      border: none;
      box-shadow: none;
      border-radius: 0;
    }
    .current-card {
      display: grid;
      gap: 8px;
    }
    .current-state {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(142,197,255,0.12);
      color: #d6ebff;
      font-size: 9px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      font-weight: 800;
    }
    .current-title {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 19px;
      line-height: 1.06;
      letter-spacing: -0.04em;
    }
    .current-copy {
      color: var(--muted);
      line-height: 1.65;
      font-size: 10px;
      white-space: pre-line;
    }
    .progress-wrap {
      display: grid;
      gap: 8px;
    }
    .progress-meta {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 10px;
    }
    .progress-bar {
      height: 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.08);
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.06);
    }
    .progress-fill {
      height: 100%;
      width: 0%;
      border-radius: 999px;
      background: linear-gradient(90deg, #8ec5ff, #cda5ff, #f0c58d);
      transition: width 0.25s ease;
    }
    .live-tags {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .live-tag {
      display: inline-flex;
      align-items: center;
      padding: 6px 9px;
      border-radius: 999px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.05);
      color: rgba(212,230,255,0.82);
      font-size: 9px;
      font-weight: 600;
    }
    .poster-stage {
      border-radius: 18px;
      overflow: hidden;
      min-height: 220px;
      background: transparent;
      position: relative;
      display: flex;
      align-items: end;
      justify-content: center;
    }
    .poster-stage::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 54% 26%, rgba(255,255,255,0.12), transparent 0 32%),
        linear-gradient(180deg, rgba(255,255,255,0.02), rgba(8,12,16,0.24));
      pointer-events: none;
      z-index: 1;
    }
    .poster-stage img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      opacity: 0.78;
      filter: saturate(0.84) brightness(0.82) contrast(0.94);
      transform: scale(1.035);
    }
    .log-card {
      margin-top: 8px;
      padding: 0;
      border-radius: 0;
      background: transparent;
      border: none;
      box-shadow: none;
      display: block;
    }
    .log-shell {
      max-height: 64px;
      overflow: auto;
      padding: 7px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.045);
      color: #f7eee8;
      font-family: "SFMono-Regular", Menlo, Consolas, monospace;
      font-size: 9px;
      line-height: 1.4;
      white-space: pre-line;
      border: 1px solid rgba(255,255,255,0.06);
      box-shadow: none;
    }
    .log-shell.empty {
      color: rgba(247, 238, 232, 0.72);
    }
    .log-entry {
      display: grid;
      grid-template-columns: 54px 1fr;
      gap: 10px;
      padding: 2px 0;
      border-bottom: none;
    }
    .log-entry:last-child {
      border-bottom: none;
    }
    .log-time {
      color: rgba(247, 238, 232, 0.52);
    }
    .log-body {
      display: flex;
      gap: 8px;
      align-items: flex-start;
      flex-wrap: wrap;
    }
    .log-pill {
      display: inline-flex;
      align-items: center;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 8px;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      font-weight: 800;
    }
    .log-pill.try { background: rgba(86, 135, 192, 0.18); color: #b9ddff; }
    .log-pill.ok { background: rgba(62, 153, 112, 0.18); color: #b9f0d2; }
    .log-pill.fail { background: rgba(197, 97, 84, 0.18); color: #ffc7bf; }
    .log-pill.info { background: rgba(186, 140, 82, 0.18); color: #ffe0b8; }
    .log-message {
      flex: 1;
      min-width: 0;
    }
    .poster-fallback {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
      text-align: center;
      color: var(--muted);
      line-height: 1.6;
      font-size: 10px;
    }
    .section-title {
      margin: 0 0 2px;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 12px;
      letter-spacing: -0.03em;
      color: rgba(245,248,253,0.62);
    }
    .section-copy {
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.65;
    }
    .poster-rail {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(98px, 1fr));
      gap: 8px;
    }
    .hero-intro {
      margin-top: 6px;
      padding: 0;
      border-radius: 0;
      background: transparent;
      border: none;
      color: rgba(216,220,227,0.64);
      line-height: 1.45;
      font-size: 9px;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .hero-alert {
      margin-top: 0;
      color: rgba(142,197,255,0.82);
      font-weight: 600;
    }
    .poster-item {
      overflow: hidden;
      background: transparent;
      border: none;
      box-shadow: none;
      border-radius: 12px;
    }
    .poster-item img {
      width: 100%;
      height: 126px;
      object-fit: cover;
      display: block;
      background: linear-gradient(135deg, rgba(142,197,255,0.12), rgba(205,165,255,0.12));
      border-radius: 12px;
    }
    .poster-meta {
      padding: 6px 4px 2px;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.6;
    }
    .poster-meta strong {
      display: block;
      color: #f4f8ff;
      font-size: 10px;
      margin-bottom: 2px;
    }
    form, .stack { display: grid; gap: 18px; }
    .section {
      padding: 16px;
      border-radius: 18px;
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.05);
      box-shadow: none;
    }
    .section h2 {
      margin: 0 0 6px;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 18px;
      letter-spacing: -0.03em;
      color: #f5f8fd;
    }
    .section-note {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 10px;
      line-height: 1.6;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    .field { display: grid; gap: 6px; }
    .field.full { grid-column: 1 / -1; }
    label {
      font-size: 11px;
      font-weight: 600;
      color: var(--ink);
    }
    input, textarea {
      width: 100%;
      border: 1px solid rgba(255,255,255,0.05);
      border-radius: 14px;
      padding: 10px 12px;
      background: rgba(255,255,255,0.045);
      color: #eef3fa;
      font: inherit;
      font-size: 11px;
    }
    input::placeholder, textarea::placeholder {
      color: #7f8ca0;
    }
    input:focus, textarea:focus {
      outline: none;
      border-color: rgba(142,197,255,0.34);
      box-shadow: 0 0 0 4px rgba(142,197,255,0.10);
    }
    .input-with-button {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
    }
    .checks {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 4px;
    }
    .check {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.05);
      background: rgba(255,255,255,0.035);
      color: var(--muted);
      font-size: 11px;
    }
    .check input {
      width: 18px;
      height: 18px;
      accent-color: var(--accent);
    }
    .hint, .status-copy {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.6;
    }
    .path-status, .preview, .run-body, .file-copy {
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.05);
      color: var(--muted);
      line-height: 1.65;
      white-space: pre-line;
      font-size: 10px;
    }
    #runStatusText {
      padding: 0;
      border-radius: 0;
      background: transparent;
      border: none;
      color: rgba(238,243,250,0.5);
      line-height: 1.6;
      font-size: 9px;
    }
    #runButtonHome,
    #runButtonHome {
      background: rgba(142,197,255,0.86);
      color: #10202f;
    }
    .path-status.warn { color: var(--danger); }
    .preview { color: #dbeeff; font-weight: 700; }
    .status { min-height: 22px; color: var(--muted); font-size: 14px; }
    .status.ok { color: var(--ok); font-weight: 700; }
    .status.warn { color: var(--danger); font-weight: 700; }
    code {
      font-family: Menlo, Consolas, monospace;
      font-size: 0.94em;
      background: rgba(255,255,255,0.08);
      color: #dbeeff;
      padding: 2px 7px;
      border-radius: 999px;
    }
    .file-actions, .history-toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      margin: 10px 0;
    }
    .task-list {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }
    .task-item {
      padding: 12px;
      display: grid;
      gap: 6px;
    }
    .task-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 11px;
    }
    .task-status {
      color: #d2e8ff;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .task-meta {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.55;
      word-break: break-word;
    }
    .task-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 4px;
    }
    dialog.task-dialog {
      border: none;
      padding: 0;
      border-radius: 28px;
      width: min(760px, calc(100vw - 32px));
      box-shadow: var(--shadow);
      background: transparent;
    }
    dialog.task-dialog::backdrop {
      background: rgba(25,20,19,0.24);
      backdrop-filter: blur(8px);
    }
    .dialog-shell {
      padding: 18px;
      background: var(--panel-strong);
      border-radius: 22px;
      border: 1px solid rgba(255,255,255,0.07);
    }
    .dialog-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      margin-bottom: 14px;
    }
    .dialog-title {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 22px;
      color: #f5f8fd;
    }
    .dialog-grid { display: grid; gap: 12px; }
    .dialog-block {
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.10);
      border: 1px solid rgba(255,255,255,0.06);
      color: var(--muted);
      line-height: 1.6;
      white-space: pre-line;
      word-break: break-word;
      font-size: 11px;
    }
    #settingsView form {
      display: grid;
      gap: 18px;
    }
    #filesView.view.active,
    #historyView.view.active,
    #docsView.view.active {
      display: grid;
      gap: 18px;
    }
    #settingsView .section,
    #filesView .panel-card,
    #historyView .panel-card,
    #historyView .task-item {
      background: transparent;
      border: none;
      box-shadow: none;
      border-radius: 0;
      padding-left: 0;
      padding-right: 0;
    }
    #settingsView .section,
    #filesView .panel-card,
    #historyView .panel-card {
      padding-top: 6px;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    #historyView .task-item {
      padding-top: 8px;
      padding-bottom: 8px;
      border-bottom: 1px solid rgba(255,255,255,0.05);
    }
    #filesView .grid-3,
    #historyView .panel-card {
      gap: 12px;
    }
    .view-head {
      display: grid;
      gap: 4px;
      padding: 2px 0 10px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      margin-bottom: 4px;
    }
    .view-kicker {
      color: rgba(142,197,255,0.78);
      font-size: 9px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-weight: 700;
    }
    .view-title {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 20px;
      line-height: 1.06;
      letter-spacing: -0.03em;
      color: #f5f8fd;
    }
    .view-note {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.65;
      max-width: 720px;
    }
    .docs-sheet {
      display: grid;
      gap: 18px;
      padding: 8px 0 24px;
    }
    .docs-block {
      display: grid;
      gap: 10px;
      padding: 4px 0 14px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .docs-block:last-child {
      border-bottom: none;
    }
    .docs-title {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: 20px;
      color: #f5f8fd;
      letter-spacing: -0.03em;
    }
    .docs-copy {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.8;
      white-space: pre-line;
      max-width: 720px;
    }
    .module-dock {
      position: fixed;
      left: 18px;
      top: 50%;
      transform: translateY(-50%);
      z-index: 5;
      display: grid;
      align-items: center;
      justify-items: start;
      padding: 8px;
      border-radius: 16px;
      background: rgba(205, 207, 210, 0.10);
      border: 1px solid rgba(255,255,255,0.10);
      box-shadow: 0 10px 28px rgba(6, 12, 20, 0.16);
      backdrop-filter: blur(24px);
      gap: 7px;
    }
    .dock-trigger {
      display: none;
    }
    .dock-options {
      display: grid;
      gap: 6px;
      max-width: none;
      max-height: none;
      overflow: visible;
      opacity: 1;
      transform: none;
    }
    .dock-button {
      position: relative;
      padding: 8px 10px;
      border-radius: 12px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.06);
      color: rgba(231,236,245,0.86);
      box-shadow: none;
      white-space: nowrap;
      font-size: 11px;
      text-align: center;
      width: 74px;
      padding-left: 26px;
    }
    .dock-button::before {
      content: "";
      position: absolute;
      left: 10px;
      top: 50%;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      transform: translateY(-50%);
      background: rgba(255,255,255,0.24);
      box-shadow: 0 0 0 1px rgba(255,255,255,0.05);
    }
    .dock-button.active {
      background: linear-gradient(135deg, rgba(255,255,255,0.12), rgba(255,255,255,0.06));
      color: #ffffff;
      border-color: rgba(142,197,255,0.18);
    }
    .dock-button.active::before {
      background: rgba(142,197,255,0.92);
      box-shadow: 0 0 10px rgba(142,197,255,0.46);
    }
    @media (max-width: 1024px) {
      .scene {
        padding: 14px;
      }
      .window-shell {
        width: min(calc(100vw - 28px), 760px);
        height: min(calc(100vh - 28px), 920px);
      }
      .app { grid-template-columns: 1fr; }
      .sidebar, .surface {
        min-height: auto;
        max-height: none;
        height: auto;
      }
      .hero-card, .grid-4, .grid-3, .grid-2, .grid { grid-template-columns: 1fr; }
      .stat-strip { display: grid; grid-template-columns: 1fr; gap: 4px; }
      .module-dock {
        left: 10px;
        top: auto;
        bottom: 10px;
        transform: none;
        width: auto;
      }
      .dock-options {
        display: flex;
        flex-wrap: wrap;
        overflow: auto;
      }
    }
    @keyframes rain-fall {
      from { transform: translate3d(0, -18px, 0); }
      to { transform: translate3d(-10px, 26px, 0); }
    }
    @keyframes rain-drift {
      from { transform: translate3d(0, 0, 0); }
      to { transform: translate3d(-12px, 8px, 0); }
    }
  </style>
</head>
<body>
  <div class="scene">
    <canvas class="rain-canvas" id="rainCanvas" aria-hidden="true"></canvas>
    <div class="rain-layer" id="rainFallback"></div>
    <div class="window-shell">
      <div class="window-topbar">
        <div class="window-title">mdcn local app</div>
      </div>
      <div class="app">
        <main class="surface">
          <div class="topbar">
            <div class="hidden-controls">
              <div class="badge" id="configPathBadge">loading config...</div>
              <button type="button" class="secondary" id="reloadButton">重新加载</button>
              <button type="button" class="secondary" id="retryFailedButton">重跑失败</button>
              <button type="button" class="primary" id="runButton">开始刮削</button>
            </div>
          </div>

          <section class="view active" id="homeView">
            <div class="hero-card">
              <div class="current-card">
                <span class="current-state" id="homeRunState">准备中</span>
                <h3 class="current-title" id="currentTaskTitle">还没有开始任务</h3>
                <div class="current-copy" id="currentTaskMeta">加载运行状态中...</div>
                <div class="hero-intro">
                  <div id="welcomeNotice">1. 填写源目录
2. 填写目标目录
3. 点击“保存并开始刮削”</div>
                  <div class="hero-alert" id="welcomeAlert">首次启动时，请先把默认示例路径改成你自己的真实目录。</div>
                </div>
                <div class="live-tags">
                  <span class="live-tag" id="currentCrawlerTag">站点: -</span>
                  <span class="live-tag" id="currentCandidateTag">候选: -</span>
                </div>
                <div class="progress-wrap">
                  <div class="progress-meta">
                    <span id="progressSummaryText">等待任务开始</span>
                    <span id="progressPercentText">0%</span>
                  </div>
                  <div class="progress-bar">
                    <div class="progress-fill" id="progressFill"></div>
                  </div>
                </div>
                <div class="actions">
                  <button type="button" class="secondary hidden-controls" id="retryFailedButtonHome">重跑失败</button>
                  <button type="button" class="primary" id="runButtonHome">立即开始</button>
                </div>
                <div class="run-body" id="runStatusText">空闲</div>
              </div>
              <div class="poster-stage">
                <img id="currentPosterImage" alt="当前海报预览" hidden />
                <div class="poster-fallback" id="currentPosterFallback">开始任务后，这里会显示当前命中的海报图。</div>
              </div>
            </div>
            <div class="stat-strip">
              <div class="stat-pill">
                <span>总任务</span>
                <strong id="totalTasksValue">0</strong>
              </div>
              <div class="stat-pill">
                <span>已完成</span>
                <strong id="completedTasksValue">0</strong>
              </div>
              <div class="stat-pill">
                <span>剩余</span>
                <strong id="remainingTasksValue">0</strong>
              </div>
              <div class="stat-pill">
                <span>失败</span>
                <strong id="failedTasksValue">0</strong>
              </div>
            </div>
            <div style="height:10px;"></div>
            <div class="log-card">
              <div class="log-shell empty" id="activityLogText">等待任务开始...</div>
            </div>
            <div style="height:10px;"></div>
            <div class="poster-rail" id="recentPosterRail"></div>
          </section>

          <section class="view" id="settingsView">
        <div class="view-head">
          <div class="view-kicker">Settings</div>
          <h2 class="view-title">设置</h2>
          <div class="view-note">管理目录、命名规则、站点来源和网络参数。这里的改动会直接影响后续刮削和整理结果。</div>
        </div>
        <form id="configForm">
          <section class="section">
            <h2>目录路径</h2>
            <p class="section-note">源目录一般放待整理视频，目标目录一般放最终媒体库。</p>
            <div class="grid">
              <div class="field full">
                <label for="source_dir">源目录</label>
                <div class="input-with-button">
                  <input id="source_dir" name="source_dir" placeholder="/path/to/failed" />
                  <button type="button" class="secondary" id="browseSourceButton">浏览…</button>
                </div>
              </div>
              <div class="field full">
                <label for="target_root">目标目录</label>
                <div class="input-with-button">
                  <input id="target_root" name="target_root" placeholder="/path/to/library" />
                  <button type="button" class="secondary" id="browseTargetButton">浏览…</button>
                </div>
              </div>
            </div>
            <div class="path-status" id="pathStatusText">正在检测目录状态...</div>
          </section>

          <section class="section">
            <h2>输出规则</h2>
            <p class="section-note">命名规则会直接影响最终媒体库目录结构。</p>
            <div class="grid">
              <div class="field full">
                <label for="folder_template">命名规则</label>
                <input id="folder_template" name="folder_template" placeholder="{number} {title}" />
                <div class="hint">可用占位符: <code>{number}</code> <code>{title}</code> <code>{studio}</code> <code>{series}</code> <code>{source}</code> <code>{year}</code> <code>{actors}</code></div>
                <div class="preview" id="previewText">MD-001 Sample Title</div>
              </div>
              <div class="field">
                <label for="max_images">最大图片数</label>
                <input id="max_images" name="max_images" type="number" min="0" step="1" />
              </div>
              <div class="field">
                <label for="extensions">视频扩展名</label>
                <input id="extensions" name="extensions" placeholder=".mp4,.mkv,.ts" />
              </div>
            </div>
            <div class="checks">
              <label class="check"><input id="write_nfo" name="write_nfo" type="checkbox" /> 写入 NFO</label>
              <label class="check"><input id="write_json" name="write_json" type="checkbox" /> 写入 JSON</label>
            </div>
          </section>

          <section class="section">
            <h2>网络设置</h2>
            <p class="section-note">如果你有代理，或需要更高容错，可以在这里统一调整。</p>
            <div class="grid">
              <div class="field full">
                <label for="proxy">代理地址</label>
                <input id="proxy" name="proxy" placeholder="http://127.0.0.1:7890" />
              </div>
              <div class="field">
                <label for="timeout">超时秒数</label>
                <input id="timeout" name="timeout" type="number" min="1" step="1" />
              </div>
              <div class="field">
                <label for="retries">重试次数</label>
                <input id="retries" name="retries" type="number" min="0" step="1" />
              </div>
            </div>
          </section>

          <section class="section">
            <h2>站点来源</h2>
            <p class="section-note">任务失败前会轮询所有启用站点。这里可以调整顺序、镜像和开关。</p>
            <div class="grid">
              <div class="field full">
                <label for="site_order">站点优先顺序</label>
                <input id="site_order" name="site_order" placeholder="avjia, tianmei, madouclub, madouqu, mdtv" />
                <div class="hint">按逗号分隔。刮削时会优先尝试前面的站点。</div>
              </div>
              <div class="field full">
                <label for="site_madouqu_base_url">MadouQu 地址</label>
                <input id="site_madouqu_base_url" name="site_madouqu_base_url" />
                <input id="site_madouqu_mirrors" name="site_madouqu_mirrors" placeholder="https://mirror1.example, https://mirror2.example" />
              </div>
              <div class="field full">
                <label for="site_mdtv_base_url">MadouTV 地址</label>
                <input id="site_mdtv_base_url" name="site_mdtv_base_url" />
                <input id="site_mdtv_mirrors" name="site_mdtv_mirrors" placeholder="https://mirror1.example, https://mirror2.example" />
              </div>
              <div class="field full">
                <label for="site_madouclub_base_url">MadouClub 地址</label>
                <input id="site_madouclub_base_url" name="site_madouclub_base_url" />
                <input id="site_madouclub_mirrors" name="site_madouclub_mirrors" placeholder="https://mirror1.example, https://mirror2.example" />
              </div>
              <div class="field full">
                <label for="site_avjia_base_url">AvJia 地址</label>
                <input id="site_avjia_base_url" name="site_avjia_base_url" />
                <input id="site_avjia_mirrors" name="site_avjia_mirrors" placeholder="https://mirror1.example, https://mirror2.example" />
              </div>
              <div class="field full">
                <label for="site_tianmei_base_url">Tianmei 地址</label>
                <input id="site_tianmei_base_url" name="site_tianmei_base_url" />
                <input id="site_tianmei_mirrors" name="site_tianmei_mirrors" placeholder="https://www.wyxk.cc, https://www.xbyc.cc" />
              </div>
            </div>
            <div class="checks">
              <label class="check"><input id="site_madouqu_enabled" name="site_madouqu_enabled" type="checkbox" /> 启用 MadouQu</label>
              <label class="check"><input id="site_mdtv_enabled" name="site_mdtv_enabled" type="checkbox" /> 启用 MadouTV</label>
              <label class="check"><input id="site_madouclub_enabled" name="site_madouclub_enabled" type="checkbox" /> 启用 MadouClub</label>
              <label class="check"><input id="site_avjia_enabled" name="site_avjia_enabled" type="checkbox" /> 启用 AvJia</label>
              <label class="check"><input id="site_tianmei_enabled" name="site_tianmei_enabled" type="checkbox" /> 启用 Tianmei</label>
            </div>
          </section>

          <div class="actions">
            <button type="button" class="secondary" id="reloadButtonBottom">重新加载</button>
            <button type="button" class="secondary" id="retryFailedButtonBottom">保存并重跑失败任务</button>
            <button type="button" class="secondary" id="runButtonBottom">保存并开始刮削</button>
            <button type="submit" class="primary">保存配置</button>
            <div class="status" id="statusText"></div>
          </div>
        </form>
          </section>

          <section class="view" id="filesView">
        <div class="view-head">
          <div class="view-kicker">Files</div>
          <h2 class="view-title">文件整理</h2>
          <div class="view-note">这个模块只做一件事：按你指定的命名规则，批量整理某个目录下的媒体文件。</div>
        </div>
        <div class="panel-card metric" style="padding:18px;">
          <div class="grid">
            <div class="field full">
              <label for="organizeDirectory">待整理目录</label>
              <div class="input-with-button">
                <input id="organizeDirectory" placeholder="/Volumes/VideoHub/国产传媒" />
                <button type="button" class="secondary" id="browseOrganizeDirectoryButton">浏览…</button>
                <button type="button" class="secondary" id="openOrganizeDirectoryButton">打开</button>
              </div>
            </div>
            <div class="field">
              <label for="organizeFolderRule">文件夹规则</label>
              <input id="organizeFolderRule" value="{number} {title}" />
              <div class="hint">示例: <code>MD-002 示例标题</code></div>
            </div>
            <div class="field">
              <label for="organizeVideoRule">视频规则</label>
              <input id="organizeVideoRule" value="{number}" />
              <div class="hint">示例: <code>MD-002.mp4</code></div>
            </div>
            <div class="field">
              <label for="organizePosterRule">海报规则</label>
              <input id="organizePosterRule" value="{number}_poster.jpg" />
              <div class="hint">统一保留单个海报文件。</div>
            </div>
          </div>
          <div class="checks">
            <label class="check"><input id="organizeRecursive" type="checkbox" checked /> 递归整理子目录</label>
          </div>
          <div class="actions">
            <button type="button" class="secondary" id="previewOrganizeButton">预览整理</button>
            <button type="button" class="primary" id="applyOrganizeButton">执行整理</button>
            <div class="status" id="organizeStatusText">等待操作</div>
          </div>
          <div class="run-body" id="organizeSummaryText">还没有预览结果。</div>
          <div class="log-shell" id="organizeLogText">点击“预览整理”查看将要执行的文件改动。</div>
        </div>
          </section>

          <section class="view" id="historyView">
        <div class="view-head">
          <div class="view-kicker">History</div>
          <h2 class="view-title">历史</h2>
          <div class="view-note">这里会保存最近任务状态、失败原因和重跑入口，方便回看每次刮削发生了什么。</div>
        </div>
        <div class="panel-card metric" style="padding:20px;">
          <div class="metric-label">任务概览</div>
          <div class="run-body" id="taskSummaryText">暂无任务记录</div>
          <div class="history-toolbar">
            <label for="taskFilter">筛选</label>
            <input id="taskFilter" name="taskFilter" value="all" list="taskFilterOptions" style="max-width: 180px;" />
            <input id="taskSearch" name="taskSearch" placeholder="搜索番号、路径、错误..." style="min-width: 220px;" />
            <datalist id="taskFilterOptions">
              <option value="all"></option>
              <option value="success"></option>
              <option value="failed"></option>
              <option value="running"></option>
            </datalist>
            <button type="button" class="secondary" id="refreshTasksButton">刷新任务</button>
          </div>
          <ul class="task-list" id="taskList"></ul>
          </div>
          </section>

          <section class="view" id="docsView">
            <div class="view-head">
              <div class="view-kicker">Docs</div>
              <h2 class="view-title">文档</h2>
              <div class="view-note">项目说明、配置建议和使用方法都集中在这里，方便直接在应用里查阅。</div>
            </div>
            <div class="docs-sheet">
              <div class="docs-block">
                <h2 class="docs-title">项目说明</h2>
                <div class="docs-copy">mdcn 是一个本地媒体整理工具。它会扫描视频文件，从多个站点抓取标题、番号、封面和相关信息，再按你的命名规则整理到目标目录里。</div>
              </div>
              <div class="docs-block">
                <h2 class="docs-title">基础设置</h2>
                <div class="docs-copy">1. 在“设置”页填写源目录和目标目录。
2. 按需要修改命名规则、图片数量、代理和重试次数。
3. 勾选要启用的站点，并调整站点顺序。</div>
              </div>
              <div class="docs-block">
                <h2 class="docs-title">使用方式</h2>
                <div class="docs-copy">1. 回到“首页”点击“立即开始”。
2. 页面会显示当前处理的文件、站点和最新过程。
3. 如果有失败任务，可以到“历史”里查看详情并重跑。</div>
              </div>
              <div class="docs-block">
                <h2 class="docs-title">文件整理</h2>
                <div class="docs-copy">“文件”页会展示源目录待处理数量、目标库目录数量，以及当前配置文件所在目录。你也可以直接从这里打开对应文件夹。</div>
              </div>
              <div class="docs-block">
                <h2 class="docs-title">注意事项</h2>
                <div class="docs-copy">首次使用时，请先确认目录路径不是示例路径。站点数据可能随时变化，如果某个任务未命中，可以稍后重试，或在历史页查看失败详情。</div>
              </div>
            </div>
          </section>
        </main>
      </div>
      <div class="module-dock">
        <button type="button" class="dock-trigger" id="dockTrigger" aria-label="切换模块">+</button>
        <div class="dock-options">
          <button type="button" class="dock-button active" data-view-target="homeView">首页</button>
          <button type="button" class="dock-button" data-view-target="settingsView">设置</button>
          <button type="button" class="dock-button" data-view-target="filesView">文件</button>
          <button type="button" class="dock-button" data-view-target="historyView">历史</button>
          <button type="button" class="dock-button" data-view-target="docsView">文档</button>
        </div>
      </div>
    </div>
  </div>

  <dialog class="task-dialog" id="taskDetailDialog">
    <div class="dialog-shell">
      <div class="dialog-header">
        <h2 class="dialog-title" id="taskDetailTitle">任务详情</h2>
        <button type="button" class="secondary" id="closeTaskDetailButton">关闭</button>
      </div>
      <div class="dialog-grid" id="taskDetailGrid"></div>
    </div>
  </dialog>

  <script>
    const fields = [
      "source_dir", "target_root", "folder_template", "max_images", "extensions",
      "site_order", "proxy", "timeout", "retries",
      "site_madouqu_base_url", "site_madouqu_mirrors",
      "site_mdtv_base_url", "site_mdtv_mirrors",
      "site_madouclub_base_url", "site_madouclub_mirrors",
      "site_avjia_base_url", "site_avjia_mirrors",
      "site_tianmei_base_url", "site_tianmei_mirrors"
    ];
    const checks = [
      "write_nfo", "write_json", "site_madouqu_enabled", "site_mdtv_enabled", "site_madouclub_enabled", "site_avjia_enabled", "site_tianmei_enabled"
    ];

    const form = document.getElementById("configForm");
    const statusText = document.getElementById("statusText");
    const configPathBadge = document.getElementById("configPathBadge");
    const welcomeNotice = document.getElementById("welcomeNotice");
    const welcomeAlert = document.getElementById("welcomeAlert");
    const pathStatusText = document.getElementById("pathStatusText");
    const previewText = document.getElementById("previewText");
    const runStatusText = document.getElementById("runStatusText");
    const taskSummaryText = document.getElementById("taskSummaryText");
    const taskList = document.getElementById("taskList");
    const taskFilter = document.getElementById("taskFilter");
    const taskSearch = document.getElementById("taskSearch");
    const taskDetailDialog = document.getElementById("taskDetailDialog");
    const taskDetailTitle = document.getElementById("taskDetailTitle");
    const taskDetailGrid = document.getElementById("taskDetailGrid");
    const organizeDirectory = document.getElementById("organizeDirectory");
    const organizeFolderRule = document.getElementById("organizeFolderRule");
    const organizeVideoRule = document.getElementById("organizeVideoRule");
    const organizePosterRule = document.getElementById("organizePosterRule");
    const organizeRecursive = document.getElementById("organizeRecursive");
    const organizeStatusText = document.getElementById("organizeStatusText");
    const organizeSummaryText = document.getElementById("organizeSummaryText");
    const organizeLogText = document.getElementById("organizeLogText");
    const rainCanvas = document.getElementById("rainCanvas");
    const rainFallback = document.getElementById("rainFallback");
    let rainMouse = { x: window.innerWidth * 0.5, y: window.innerHeight * 0.78, down: false };

    function initRainShader() {
      if (!rainCanvas) return;
      const gl = rainCanvas.getContext("webgl2", { antialias: true, alpha: true, premultipliedAlpha: false });
      if (!gl) {
        return;
      }

      const vertexSource = `#version 300 es
        precision highp float;
        const vec2 positions[3] = vec2[3](
          vec2(-1.0, -1.0),
          vec2(3.0, -1.0),
          vec2(-1.0, 3.0)
        );
        void main() {
          gl_Position = vec4(positions[gl_VertexID], 0.0, 1.0);
        }
      `;

      const fragmentSource = `#version 300 es
        precision highp float;
        out vec4 fragColor;

        uniform vec3 iResolution;
        uniform float iTime;
        uniform vec4 iMouse;
        uniform sampler2D iChannel0;

        #define S(a, b, t) smoothstep(a, b, t)
        #define HAS_HEART
        #define USE_POST_PROCESSING

        vec3 N13(float p) {
          vec3 p3 = fract(vec3(p) * vec3(.1031,.11369,.13787));
          p3 += dot(p3, p3.yzx + 19.19);
          return fract(vec3((p3.x + p3.y)*p3.z, (p3.x+p3.z)*p3.y, (p3.y+p3.z)*p3.x));
        }

        float N(float t) {
          return fract(sin(t*12345.564)*7658.76);
        }

        float Saw(float b, float t) {
          return S(0., b, t)*S(1., b, t);
        }

        vec2 DropLayer2(vec2 uv, float t) {
          vec2 UV = uv;
          uv.y += t*0.75;
          vec2 a = vec2(6., 1.);
          vec2 grid = a*2.;
          vec2 id = floor(uv*grid);
          float colShift = N(id.x);
          uv.y += colShift;
          id = floor(uv*grid);
          vec3 n = N13(id.x*35.2+id.y*2376.1);
          vec2 st = fract(uv*grid)-vec2(.5, 0);
          float x = n.x-.5;
          float y = UV.y*20.;
          float wiggle = sin(y+sin(y));
          x += wiggle*(.5-abs(x))*(n.z-.5);
          x *= .7;
          float ti = fract(t+n.z);
          y = (Saw(.85, ti)-.5)*.9+.5;
          vec2 p = vec2(x, y);
          float d = length((st-p)*a.yx);
          float mainDrop = S(.4, .0, d);
          float r = sqrt(S(1., y, st.y));
          float cd = abs(st.x-x);
          float trail = S(.23*r, .15*r*r, cd);
          float trailFront = S(-.02, .02, st.y-y);
          trail *= trailFront*r*r;
          y = UV.y;
          float trail2 = S(.2*r, .0, cd);
          float droplets = max(0., (sin(y*(1.-y)*120.)-st.y))*trail2*trailFront*n.z;
          y = fract(y*10.)+(st.y-.5);
          float dd = length(st-vec2(x, y));
          droplets = S(.3, 0., dd);
          float m = mainDrop+droplets*r*trailFront;
          return vec2(m, trail);
        }

        float StaticDrops(vec2 uv, float t) {
          uv *= 40.;
          vec2 id = floor(uv);
          uv = fract(uv)-.5;
          vec3 n = N13(id.x*107.45+id.y*3543.654);
          vec2 p = (n.xy-.5)*.7;
          float d = length(uv-p);
          float fade = Saw(.025, fract(t+n.z));
          float c = S(.3, 0., d)*fract(n.z*10.)*fade;
          return c;
        }

        vec2 Drops(vec2 uv, float t, float l0, float l1, float l2) {
          float s = StaticDrops(uv, t)*l0;
          vec2 m1 = DropLayer2(uv, t)*l1;
          vec2 m2 = DropLayer2(uv*1.85, t)*l2;
          float c = s+m1.x+m2.x;
          c = S(.3, 1., c);
          return vec2(c, max(m1.y*l0, m2.y*l1));
        }

        void mainImage(out vec4 outColor, in vec2 fragCoord) {
          vec2 uv = (fragCoord.xy-.5*iResolution.xy) / iResolution.y;
          vec2 UV = fragCoord.xy/iResolution.xy;
          vec3 M = iMouse.xyz/iResolution.xyz;
          float T = iTime+M.x*2.;
          #ifdef HAS_HEART
          T = mod(iTime, 102.);
          T = mix(T, M.x*102., M.z>0.?1.:0.);
          #endif
          float t = T*.2;
          float rainAmount = iMouse.z>0. ? M.y : sin(T*.05)*.3+.7;
          float maxBlur = mix(3., 6., rainAmount);
          float minBlur = 2.;
          float story = 0.;
          float heart = 0.;
          float zoom = 0.0;
          #ifdef HAS_HEART
          story = S(0., 70., T);
          t = min(1., T/70.);
          t = 1.-t;
          t = (1.-t*t)*70.;
          zoom= mix(.3, 1.2, story);
          uv *=zoom;
          minBlur = 4.+S(.5, 1., story)*3.;
          maxBlur = 6.+S(.5, 1., story)*1.5;
          vec2 hv = uv-vec2(.0, -.1);
          hv.x *= .5;
          float s = S(110., 70., T);
          hv.y-=sqrt(abs(hv.x))*.5*s;
          heart = length(hv);
          heart = S(.4*s, .2*s, heart)*s;
          rainAmount = heart;
          maxBlur-=heart;
          uv *= 1.5;
          t *= .25;
          #else
          zoom = -cos(T*.2);
          uv *= .7+zoom*.3;
          #endif
          UV = (UV-.5)*(.9+zoom*.1)+.5;
          float staticDrops = S(-.5, 1., rainAmount)*2.;
          float layer1 = S(.25, .75, rainAmount);
          float layer2 = S(.0, .5, rainAmount);
          vec2 c = Drops(uv, t, staticDrops, layer1, layer2);
          vec2 e = vec2(.001, 0.);
          float cx = Drops(uv+e, t, staticDrops, layer1, layer2).x;
          float cy = Drops(uv+e.yx, t, staticDrops, layer1, layer2).x;
          vec2 n = vec2(cx-c.x, cy-c.x);
          #ifdef HAS_HEART
          n *= 1.-S(60., 85., T);
          c.y *= 1.-S(80., 100., T)*.8;
          #endif
          float focus = mix(maxBlur-c.y, minBlur, S(.1, .2, c.x));
          vec3 col = textureLod(iChannel0, clamp(UV+n, 0.001, 0.999), focus).rgb;
          #ifdef USE_POST_PROCESSING
          t = (T+3.)*.5;
          float colFade = sin(t*.2)*.5+.5+story;
          col *= mix(vec3(1.), vec3(.8, .9, 1.3), colFade);
          float fade = S(0., 10., T);
          float lightning = sin(t*sin(t*10.));
          lightning *= pow(max(0., sin(t+sin(t))), 10.);
          col *= 1.+lightning*fade*mix(1., .1, story*story);
          vec2 v = UV-.5;
          col *= 1.-dot(v, v);
          #ifdef HAS_HEART
          col = mix(pow(col, vec3(1.2)), col, heart);
          fade *= S(102., 97., T);
          #endif
          col *= fade;
          #endif
          outColor = vec4(col, 1.);
        }

        void main() {
          mainImage(fragColor, gl_FragCoord.xy);
        }
      `;

      const program = createProgram(gl, vertexSource, fragmentSource);
      if (!program) {
        return;
      }

      const uniformLocations = {
        iResolution: gl.getUniformLocation(program, "iResolution"),
        iTime: gl.getUniformLocation(program, "iTime"),
        iMouse: gl.getUniformLocation(program, "iMouse"),
        iChannel0: gl.getUniformLocation(program, "iChannel0"),
      };

      const texture = gl.createTexture();
      const bgCanvas = document.createElement("canvas");
      const bgCtx = bgCanvas.getContext("2d");

      if (!texture || !bgCtx) {
        return;
      }

      function resize() {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const width = Math.max(1, Math.floor(window.innerWidth * dpr));
        const height = Math.max(1, Math.floor(window.innerHeight * dpr));
        if (rainCanvas.width !== width || rainCanvas.height !== height) {
          rainCanvas.width = width;
          rainCanvas.height = height;
          rainCanvas.style.width = `${window.innerWidth}px`;
          rainCanvas.style.height = `${window.innerHeight}px`;
        }
        gl.viewport(0, 0, rainCanvas.width, rainCanvas.height);
      }

      function buildBackgroundTexture() {
        bgCanvas.width = 1024;
        bgCanvas.height = 1024;
        const gradient = bgCtx.createLinearGradient(0, 0, bgCanvas.width, bgCanvas.height);
        gradient.addColorStop(0, "#0f1824");
        gradient.addColorStop(0.45, "#172434");
        gradient.addColorStop(1, "#2e3947");
        bgCtx.fillStyle = gradient;
        bgCtx.fillRect(0, 0, bgCanvas.width, bgCanvas.height);

        const glowA = bgCtx.createRadialGradient(220, 180, 0, 220, 180, 240);
        glowA.addColorStop(0, "rgba(142,197,255,0.34)");
        glowA.addColorStop(1, "rgba(142,197,255,0)");
        bgCtx.fillStyle = glowA;
        bgCtx.fillRect(0, 0, bgCanvas.width, bgCanvas.height);

        const glowB = bgCtx.createRadialGradient(780, 240, 0, 780, 240, 280);
        glowB.addColorStop(0, "rgba(240,197,141,0.26)");
        glowB.addColorStop(1, "rgba(240,197,141,0)");
        bgCtx.fillStyle = glowB;
        bgCtx.fillRect(0, 0, bgCanvas.width, bgCanvas.height);

        const glowC = bgCtx.createRadialGradient(620, 740, 0, 620, 740, 320);
        glowC.addColorStop(0, "rgba(160,126,255,0.16)");
        glowC.addColorStop(1, "rgba(160,126,255,0)");
        bgCtx.fillStyle = glowC;
        bgCtx.fillRect(0, 0, bgCanvas.width, bgCanvas.height);

        bgCtx.strokeStyle = "rgba(255,255,255,0.05)";
        bgCtx.lineWidth = 1;
        for (let i = 0; i < 80; i += 1) {
          const x = (i * 67) % bgCanvas.width;
          bgCtx.beginPath();
          bgCtx.moveTo(x, 0);
          bgCtx.lineTo(x - 200, bgCanvas.height);
          bgCtx.stroke();
        }

        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bgCanvas);
        gl.generateMipmap(gl.TEXTURE_2D);
      }

      function render(now) {
        resize();
        gl.useProgram(program);
        gl.uniform3f(uniformLocations.iResolution, rainCanvas.width, rainCanvas.height, 1.0);
        gl.uniform1f(uniformLocations.iTime, now * 0.001);
        gl.uniform4f(
          uniformLocations.iMouse,
          rainMouse.x * (window.devicePixelRatio || 1),
          (window.innerHeight - rainMouse.y) * (window.devicePixelRatio || 1),
          rainMouse.down ? 1.0 : 0.0,
          0.0
        );
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.uniform1i(uniformLocations.iChannel0, 0);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        requestAnimationFrame(render);
      }

      window.addEventListener("resize", resize);
      window.addEventListener("pointermove", (event) => {
        rainMouse.x = event.clientX;
        rainMouse.y = event.clientY;
      });
      window.addEventListener("pointerdown", () => { rainMouse.down = true; });
      window.addEventListener("pointerup", () => { rainMouse.down = false; });

      buildBackgroundTexture();
      rainFallback.classList.add("hidden");
      requestAnimationFrame(render);
    }

    function createProgram(gl, vertexSource, fragmentSource) {
      const vertexShader = compileShader(gl, gl.VERTEX_SHADER, vertexSource);
      const fragmentShader = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
      if (!vertexShader || !fragmentShader) {
        return null;
      }
      const program = gl.createProgram();
      if (!program) return null;
      gl.attachShader(program, vertexShader);
      gl.attachShader(program, fragmentShader);
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        return null;
      }
      return program;
    }

    function compileShader(gl, type, source) {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        return null;
      }
      return shader;
    }

    function collectPayload() {
      const payload = {};
      for (const name of fields) {
        payload[name] = document.getElementById(name).value;
      }
      for (const name of checks) {
        payload[name] = document.getElementById(name).checked;
      }
      return payload;
    }

    function isPlaceholderPath(value) {
      if (!value) return true;
      const normalized = String(value).trim().toLowerCase();
      return normalized.startsWith("/path/to/") || normalized === "/path/to/failed" || normalized === "/path/to/library";
    }

    function updateWelcomeState() {
      const sourceDir = document.getElementById("source_dir").value;
      const targetRoot = document.getElementById("target_root").value;
      const sourceReady = !isPlaceholderPath(sourceDir);
      const targetReady = !isPlaceholderPath(targetRoot);
      welcomeNotice.textContent = [
        `${sourceReady ? "1. 已设置" : "1. 待设置"} 源目录`,
        `${targetReady ? "2. 已设置" : "2. 待设置"} 目标目录`,
        `${sourceReady && targetReady ? "3. 现在可以点击“保存并开始刮削”" : "3. 先把两个目录都改成真实路径"}`,
      ].join("\\n");
      if (sourceReady && targetReady) {
        welcomeAlert.textContent = "目录已经准备好，可以从首页直接启动任务。";
        welcomeAlert.style.color = "var(--ok)";
      } else {
        welcomeAlert.textContent = "首次启动时，请先把默认示例路径改成你自己的真实目录。";
        welcomeAlert.style.color = "var(--accent-deep)";
      }
    }

    function switchView(viewId) {
      document.querySelectorAll("[data-view-target]").forEach((button) => {
        button.classList.toggle("active", button.dataset.viewTarget === viewId);
      });
      document.querySelectorAll(".view").forEach((view) => {
        view.classList.toggle("active", view.id === viewId);
      });
    }

    async function validatePaths() {
      const sourceDir = document.getElementById("source_dir").value || "";
      const targetRoot = document.getElementById("target_root").value || "";
      const response = await fetch(`/api/validate-paths?source_dir=${encodeURIComponent(sourceDir)}&target_root=${encodeURIComponent(targetRoot)}`);
      const data = await response.json();
      pathStatusText.textContent = [`源目录: ${data.source_message || "-"}`, `目标目录: ${data.target_message || "-"}`].join("\\n");
      pathStatusText.className = data.can_run ? "path-status" : "path-status warn";
      return data;
    }

    async function browseDirectory(fieldId) {
      const input = document.getElementById(fieldId);
      const initialPath = isPlaceholderPath(input.value || "") ? "" : (input.value || "");
      const response = await fetch("/api/pick-directory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initial_path: initialPath }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        statusText.textContent = data.error || "目录选择器没有成功打开。";
        statusText.className = "status warn";
        return;
      }
      if (data.selected_path) {
        input.value = data.selected_path;
        if (fieldId === "organizeDirectory") {
          setOrganizeStatus("目录已选择。", "status ok");
        } else {
          updateWelcomeState();
          await validatePaths();
          statusText.textContent = "目录已选择。";
          statusText.className = "status ok";
        }
      }
    }

    async function openSystemPath(path) {
      if (!path) return;
      await fetch("/api/open-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
    }

    function setOrganizeStatus(text, tone = "status") {
      if (!organizeStatusText) return;
      organizeStatusText.textContent = text;
      organizeStatusText.className = tone;
    }

    function renderOrganizeResult(result) {
      if (!organizeSummaryText || !organizeLogText) return;
      const summary = result.summary || {};
      organizeSummaryText.textContent = [
        `扫描文件夹: ${summary.folders_scanned || 0}`,
        `将调整文件夹: ${summary.folders_updated || 0}`,
        `视频重命名: ${summary.videos_renamed || 0}`,
        `海报重命名: ${summary.posters_renamed || 0}`,
        `海报删除: ${summary.posters_deleted || 0}`,
        `NFO重命名: ${summary.nfo_renamed || 0}`,
        `NFO删除: ${summary.nfo_deleted || 0}`,
        `跳过(缺番号): ${summary.skipped_no_number || 0}`,
        `跳过(缺标题): ${summary.skipped_no_title || 0}`,
      ].join("\\n");

      const details = result.details || [];
      if (!details.length) {
        organizeLogText.textContent = "没有需要调整的文件。";
        return;
      }
      const lines = [];
      for (const item of details.slice(0, 40)) {
        lines.push(`[${item.number || "-"}] ${item.title || "-"} @ ${item.folder || "-"}`);
        for (const action of (item.actions || []).slice(0, 8)) {
          lines.push(`  - ${action}`);
        }
      }
      if ((result.details_total || 0) > details.length) {
        lines.push(`... 还有 ${result.details_total - details.length} 项未展示`);
      }
      organizeLogText.textContent = lines.join("\\n");
    }

    async function runOrganizer(applyChanges) {
      const directory = (organizeDirectory?.value || "").trim();
      if (!directory) {
        setOrganizeStatus("请先填写待整理目录。", "status warn");
        return;
      }
      const payload = {
        directory,
        folder_rule: (organizeFolderRule?.value || "{number} {title}").trim(),
        video_rule: (organizeVideoRule?.value || "{number}").trim(),
        poster_rule: (organizePosterRule?.value || "{number}_poster.jpg").trim(),
        recursive: Boolean(organizeRecursive?.checked),
        apply: Boolean(applyChanges),
      };
      setOrganizeStatus(applyChanges ? "正在执行整理..." : "正在生成预览...", "status warn");
      const response = await fetch("/api/files/organize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        setOrganizeStatus(data.error || "整理失败。", "status warn");
        return;
      }
      renderOrganizeResult(data);
      setOrganizeStatus(applyChanges ? "整理完成。" : "预览生成完成。", "status ok");
    }

    async function refreshPreview() {
      const template = document.getElementById("folder_template").value || "{number} {title}";
      const response = await fetch(`/api/preview?template=${encodeURIComponent(template)}`);
      const data = await response.json();
      previewText.textContent = data.preview;
    }

    function renderTasks(data) {
      const summary = data.summary ?? {};
      const recent = data.recent ?? [];
      taskSummaryText.textContent = `success=${summary.success ?? 0} failed=${summary.failed ?? 0} running=${summary.running ?? 0}`;
      taskList.innerHTML = "";
      if (!recent.length) {
        const item = document.createElement("li");
        item.className = "task-item";
        item.textContent = "还没有任务记录。";
        taskList.appendChild(item);
        return;
      }
      for (const task of recent) {
        const item = document.createElement("li");
        item.className = "task-item";
        const title = [task.number, task.title].filter(Boolean).join(" · ") || task.video_path || "unknown";
        const reason = task.reason ? ` / ${task.reason}` : "";
        item.innerHTML = `
          <div class="task-head">
            <span class="task-status">${task.status}${reason}</span>
            <span>${task.updated_at || "-"}</span>
          </div>
          <div class="task-meta">${title}</div>
          <div class="task-meta">源文件: ${task.video_path || "-"}</div>
          <div class="task-meta">输出目录: ${task.target_dir || "-"}</div>
          <div class="task-meta">来源站点: ${task.source || "-"}</div>
          <div class="task-meta">详情: ${task.detail || "-"}</div>
        `;
        const actions = document.createElement("div");
        actions.className = "task-actions";
        const detailButton = document.createElement("button");
        detailButton.type = "button";
        detailButton.className = "secondary";
        detailButton.textContent = "查看详情";
        detailButton.addEventListener("click", () => openTaskDetail(task.video_path));
        actions.appendChild(detailButton);
        if (task.status === "failed") {
          const retryButton = document.createElement("button");
          retryButton.type = "button";
          retryButton.className = "secondary";
          retryButton.textContent = "重跑这条";
          retryButton.addEventListener("click", () => retrySingleTask(task.video_path));
          actions.appendChild(retryButton);
        }
        item.appendChild(actions);
        taskList.appendChild(item);
      }
    }

    function renderDashboard(data) {
      const run = data.run || {};
      const totals = data.totals || {};
      const total = run.queue_total || totals.total || 0;
      const completed = run.processed || 0;
      const remaining = Math.max((run.remaining ?? (total - completed)), 0);
      const failed = run.last_stats?.failed ?? totals.failed ?? 0;
      const progressPercent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;

      document.getElementById("totalTasksValue").textContent = String(total);
      document.getElementById("completedTasksValue").textContent = String(completed);
      document.getElementById("remainingTasksValue").textContent = String(remaining);
      document.getElementById("failedTasksValue").textContent = String(failed);

      const currentTitle = [run.current_number, run.current_title].filter(Boolean).join(" · ") || run.current_label || "还没有开始任务";
      document.getElementById("currentTaskTitle").textContent = currentTitle;
      document.getElementById("homeRunState").textContent = run.running ? "正在刮削" : "等待启动";
      document.getElementById("currentCrawlerTag").textContent = `站点: ${run.current_crawler || "-"}`;
      document.getElementById("currentCandidateTag").textContent = `候选: ${run.current_candidate || "-"}`;
      document.getElementById("progressSummaryText").textContent = total > 0 ? `${completed}/${total} 已处理` : "等待任务开始";
      document.getElementById("progressPercentText").textContent = `${progressPercent}%`;
      document.getElementById("progressFill").style.width = `${progressPercent}%`;

      const lines = [
        `当前文件: ${run.current_video || "-"}`,
        `来源站点: ${run.current_source || "-"}`,
        `目标目录: ${run.current_target_dir || "-"}`,
        `开始时间: ${run.started_at || "-"}`,
        `结束时间: ${run.finished_at || "-"}`,
      ];
      document.getElementById("currentTaskMeta").textContent = lines.join("\\n");

      const statusLines = [
        `状态: ${run.message || "idle"}`,
        `总量: ${total}`,
        `已完成: ${completed}`,
        `剩余: ${remaining}`,
        `失败: ${failed}`,
      ];
      if (run.last_error) statusLines.push(`错误: ${run.last_error}`);
      runStatusText.textContent = statusLines.join("\\n");

      const posterImage = document.getElementById("currentPosterImage");
      const posterFallback = document.getElementById("currentPosterFallback");
      const currentPosterUrl = run.current_poster_url || "";
      if (currentPosterUrl) {
        posterImage.src = currentPosterUrl;
        posterImage.hidden = false;
        posterFallback.hidden = true;
      } else {
        posterImage.hidden = true;
        posterFallback.hidden = false;
      }

      const logText = document.getElementById("activityLogText");
      const activityLog = (run.activity_log || []).slice(-4);
      if (activityLog.length) {
        logText.innerHTML = activityLog.map((line) => formatLogEntry(line)).join("");
        logText.classList.remove("empty");
        logText.scrollTop = logText.scrollHeight;
      } else {
        logText.textContent = "等待任务开始...";
        logText.classList.add("empty");
      }

      const rail = document.getElementById("recentPosterRail");
      rail.innerHTML = "";
      const posters = data.recent_posters || [];
      if (!posters.length) {
        const empty = document.createElement("div");
        empty.className = "poster-item";
        empty.innerHTML = `<div class="poster-meta"><strong>还没有最近成果</strong>开始刮削后，最近成功入库的海报会出现在这里。</div>`;
        rail.appendChild(empty);
      } else {
        for (const item of posters) {
          const card = document.createElement("div");
          card.className = "poster-item";
          card.innerHTML = `
            <img src="${item.poster_url}" alt="${item.number || item.title || "poster"}" />
            <div class="poster-meta">
              <strong>${[item.number, item.title].filter(Boolean).join(" · ") || "Untitled"}</strong>
              <div>${item.source || "-"}</div>
            </div>
          `;
          rail.appendChild(card);
        }
      }

    }

    async function loadDashboard() {
      const response = await fetch("/api/dashboard");
      const data = await response.json();
      renderDashboard(data);
      renderTasks(data.tasks || { summary: {}, recent: [] });
    }

    async function loadTasks() {
      const status = taskFilter.value || "all";
      const query = taskSearch.value || "";
      const response = await fetch(`/api/tasks?status=${encodeURIComponent(status)}&query=${encodeURIComponent(query)}`);
      const data = await response.json();
      renderTasks(data);
    }

    async function openTaskDetail(videoPath) {
      const response = await fetch(`/api/task?video_path=${encodeURIComponent(videoPath)}`);
      const data = await response.json();
      if (!data.ok) {
        statusText.textContent = data.error || "读取任务详情失败。";
        return;
      }
      const task = data.task;
      taskDetailTitle.textContent = [task.number, task.title].filter(Boolean).join(" · ") || task.video_path || "任务详情";
      taskDetailGrid.innerHTML = "";
      [
        ["状态", task.status || "-"],
        ["更新时间", task.updated_at || "-"],
        ["源文件", task.video_path || "-"],
        ["输出目录", task.target_dir || "-"],
        ["来源站点", task.source || "-"],
        ["失败原因", task.reason || "-"],
        ["详情", task.detail || "-"],
      ].forEach(([label, value]) => {
        const block = document.createElement("div");
        block.className = "dialog-block";
        block.textContent = `${label}: ${value}`;
        taskDetailGrid.appendChild(block);
      });
      taskDetailDialog.showModal();
    }

    async function loadConfig() {
      statusText.textContent = "正在读取配置...";
      const response = await fetch("/api/config");
      const data = await response.json();
      configPathBadge.textContent = data.config_path;
      document.getElementById("source_dir").value = data.source.dir ?? "";
      document.getElementById("target_root").value = data.target.root ?? "";
      if (organizeDirectory && !organizeDirectory.value) {
        organizeDirectory.value = data.target.root ?? "";
      }
      document.getElementById("folder_template").value = data.output.folder_template ?? "{number} {title}";
      document.getElementById("max_images").value = data.output.max_images ?? 6;
      document.getElementById("extensions").value = (data.scanner.extensions ?? []).join(", ");
      document.getElementById("site_order").value = (data.priority.site_order ?? []).join(", ");
      document.getElementById("proxy").value = data.network.proxy ?? "";
      document.getElementById("timeout").value = data.network.timeout ?? 20;
      document.getElementById("retries").value = data.network.retries ?? 2;
      document.getElementById("write_nfo").checked = Boolean(data.output.write_nfo);
      document.getElementById("write_json").checked = Boolean(data.output.write_json);
      document.getElementById("site_madouqu_enabled").checked = Boolean(data.sites.madouqu?.enabled);
      document.getElementById("site_mdtv_enabled").checked = Boolean(data.sites.mdtv?.enabled);
      document.getElementById("site_madouclub_enabled").checked = Boolean(data.sites.madouclub?.enabled);
      document.getElementById("site_avjia_enabled").checked = Boolean(data.sites.avjia?.enabled);
      document.getElementById("site_tianmei_enabled").checked = Boolean(data.sites.tianmei?.enabled);
      document.getElementById("site_madouqu_base_url").value = data.sites.madouqu?.base_url ?? "";
      document.getElementById("site_madouqu_mirrors").value = (data.sites.madouqu?.mirrors ?? []).join(", ");
      document.getElementById("site_mdtv_base_url").value = data.sites.mdtv?.base_url ?? "";
      document.getElementById("site_mdtv_mirrors").value = (data.sites.mdtv?.mirrors ?? []).join(", ");
      document.getElementById("site_madouclub_base_url").value = data.sites.madouclub?.base_url ?? "";
      document.getElementById("site_madouclub_mirrors").value = (data.sites.madouclub?.mirrors ?? []).join(", ");
      document.getElementById("site_avjia_base_url").value = data.sites.avjia?.base_url ?? "";
      document.getElementById("site_avjia_mirrors").value = (data.sites.avjia?.mirrors ?? []).join(", ");
      document.getElementById("site_tianmei_base_url").value = data.sites.tianmei?.base_url ?? "";
      document.getElementById("site_tianmei_mirrors").value = (data.sites.tianmei?.mirrors ?? []).join(", ");
      updateWelcomeState();
      await validatePaths();
      await refreshPreview();
      await loadDashboard();
      statusText.textContent = "配置已加载。";
      statusText.className = "status";
    }

    async function saveConfig(event) {
      event.preventDefault();
      const payload = collectPayload();
      statusText.textContent = "正在保存...";
      const response = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (result.ok) {
        statusText.textContent = "保存成功。";
        statusText.className = "status ok";
        await refreshPreview();
        await loadDashboard();
      } else {
        statusText.textContent = "保存失败。";
      }
    }

    function formatLogEntry(line) {
      const match = /^\\[(.*?)\\]\\s*(.*)$/.exec(line || "");
      const time = match ? match[1] : "";
      const message = match ? match[2] : (line || "");
      let tone = "info";
      let label = "INFO";
      if (message.startsWith("Checking ")) {
        tone = "try";
        label = "TRY";
      } else if (message.startsWith("Matched ")) {
        tone = "ok";
        label = "HIT";
      } else if (message.startsWith("Miss on ")) {
        tone = "fail";
        label = "MISS";
      } else if (message.includes("failed")) {
        tone = "fail";
        label = "FAIL";
      } else if (message.startsWith("Start video")) {
        tone = "info";
        label = "TASK";
      }
      return `
        <div class="log-entry">
          <div class="log-time">${time || "--:--:--"}</div>
          <div class="log-body">
            <span class="log-pill ${tone}">${label}</span>
            <span class="log-message">${escapeHtml(message)}</span>
          </div>
        </div>
      `;
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    async function saveAndRun(mode) {
      const payload = collectPayload();
      const pathValidation = await validatePaths();
      if (!pathValidation.can_run) {
        statusText.textContent = "目录检查未通过，请先修正源目录或目标目录。";
        statusText.className = "status warn";
        switchView("settingsView");
        return;
      }
      payload.mode = mode;
      statusText.textContent = mode === "retry_failed" ? "正在保存并启动失败任务重跑..." : "正在保存并启动刮削...";
      statusText.className = "status warn";
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      await loadDashboard();
      if (result.ok) {
        statusText.textContent = mode === "retry_failed" ? "已启动失败任务重跑。" : "已启动刮削任务。";
        statusText.className = "status ok";
        switchView("homeView");
      } else {
        statusText.textContent = result.error || "任务启动失败。";
      }
    }

    async function retrySingleTask(videoPath) {
      statusText.textContent = "正在启动单条失败任务重跑...";
      statusText.className = "status warn";
      const response = await fetch("/api/tasks/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: videoPath }),
      });
      const result = await response.json();
      await loadDashboard();
      if (result.ok) {
        statusText.textContent = "已启动单条任务重跑。";
        statusText.className = "status ok";
        switchView("homeView");
      } else {
        statusText.textContent = result.error || "单条任务启动失败。";
      }
    }

    document.querySelectorAll("[data-view-target]").forEach((button) => {
      button.addEventListener("click", () => switchView(button.dataset.viewTarget));
    });
    document.getElementById("reloadButton").addEventListener("click", loadConfig);
    document.getElementById("reloadButtonBottom").addEventListener("click", loadConfig);
    document.getElementById("browseSourceButton").addEventListener("click", () => browseDirectory("source_dir"));
    document.getElementById("browseTargetButton").addEventListener("click", () => browseDirectory("target_root"));
    document.getElementById("browseOrganizeDirectoryButton").addEventListener("click", () => browseDirectory("organizeDirectory"));
    document.getElementById("openOrganizeDirectoryButton").addEventListener("click", () => openSystemPath(organizeDirectory?.value || ""));
    document.getElementById("previewOrganizeButton").addEventListener("click", () => runOrganizer(false));
    document.getElementById("applyOrganizeButton").addEventListener("click", () => runOrganizer(true));
    document.getElementById("runButton").addEventListener("click", () => saveAndRun("scrape"));
    document.getElementById("runButtonHome").addEventListener("click", () => saveAndRun("scrape"));
    document.getElementById("runButtonBottom").addEventListener("click", () => saveAndRun("scrape"));
    document.getElementById("retryFailedButton").addEventListener("click", () => saveAndRun("retry_failed"));
    document.getElementById("retryFailedButtonHome").addEventListener("click", () => saveAndRun("retry_failed"));
    document.getElementById("retryFailedButtonBottom").addEventListener("click", () => saveAndRun("retry_failed"));
    document.getElementById("refreshTasksButton").addEventListener("click", loadTasks);
    document.getElementById("closeTaskDetailButton").addEventListener("click", () => taskDetailDialog.close());
    document.getElementById("folder_template").addEventListener("input", refreshPreview);
    document.getElementById("source_dir").addEventListener("input", async () => { updateWelcomeState(); await validatePaths(); });
    document.getElementById("target_root").addEventListener("input", async () => { updateWelcomeState(); await validatePaths(); });
    taskFilter.addEventListener("change", loadTasks);
    taskSearch.addEventListener("input", loadTasks);
    form.addEventListener("submit", saveConfig);

    initRainShader();
    loadConfig();
    setInterval(async () => {
      await loadDashboard();
    }, 2000);
  </script>
</body>
</html>
"""
