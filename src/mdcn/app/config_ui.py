"""Lightweight local HTML config UI."""

from __future__ import annotations

import asyncio
import json
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from mdcn.app.bootstrap import build_orchestrator
from mdcn.config import AppConfig, PathsConfig, build_config_from_dict, config_to_dict, load_config, save_config
from mdcn.output.naming import preview_folder_name
from mdcn.storage.task_repo import TaskRepository


@dataclass(slots=True)
class ConfigUiRunState:
    running: bool = False
    mode: str = ""
    message: str = "idle"
    last_error: str = ""
    last_stats: dict[str, int] = field(default_factory=lambda: {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0})
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
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def start(self, mode: str) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.mode = mode
            self.message = _mode_label(mode) + " is running"
            self.last_error = ""
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
            self.finished_at = _timestamp()

    def fail(self, mode: str, error: str) -> None:
        with self._lock:
            self.running = False
            self.mode = mode
            self.message = _mode_label(mode) + " failed"
            self.last_error = error
            self.finished_at = _timestamp()


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


def _start_background_run(
    run_state: ConfigUiRunState,
    config_path: Path,
    mode: str,
    *,
    video_paths: list[str] | None = None,
) -> bool:
    if not run_state.start(mode):
        return False

    def worker() -> None:
        try:
            config = load_config(config_path)
            orchestrator = build_orchestrator(config)
            if mode == "retry_failed":
                stats = asyncio.run(orchestrator.retry_failed())
            elif mode == "retry_selected":
                stats = asyncio.run(orchestrator.retry_video_paths(video_paths or []))
            else:
                stats = asyncio.run(orchestrator.run())
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
    if open_browser:
        webbrowser.open(f"http://{host}:{port}", new=1, autoraise=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return server


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
            if parsed.path == "/api/config":
                _ensure_config_exists(config_path)
                config = load_config(config_path)
                payload = config_to_dict(config)
                payload["config_path"] = str(config_path)
                self._send_json(payload)
                return
            if parsed.path == "/api/preview":
                query = parse_qs(parsed.query)
                template = query.get("template", ["{number} {title}"])[0]
                self._send_json({"preview": preview_folder_name(template)})
                return
            if parsed.path == "/api/run-status":
                self._send_json(run_state.snapshot())
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
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in ("/api/config", "/api/run", "/api/tasks/retry"):
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw_body)
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


def render_config_ui_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>mdcn Config Studio</title>
  <style>
    :root {
      --bg: #f5efe3;
      --panel: #fffaf2;
      --ink: #1f2421;
      --muted: #5f675f;
      --line: #d7ccb7;
      --accent: #b5472f;
      --accent-2: #244b45;
      --ok: #255f4a;
      --shadow: 0 24px 60px rgba(55, 38, 17, 0.14);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI Variable", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(181, 71, 47, 0.14), transparent 28%),
        radial-gradient(circle at 85% 15%, rgba(36, 75, 69, 0.12), transparent 22%),
        linear-gradient(180deg, #f7f1e6 0%, #efe6d6 100%);
    }
    .shell {
      width: min(1120px, calc(100vw - 32px));
      margin: 32px auto;
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 24px;
    }
    .hero, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
    }
    .hero {
      padding: 28px;
      position: sticky;
      top: 24px;
      align-self: start;
      overflow: hidden;
    }
    .hero::after {
      content: "";
      position: absolute;
      inset: auto -40px -40px auto;
      width: 180px;
      height: 180px;
      background: radial-gradient(circle, rgba(181, 71, 47, 0.18), transparent 70%);
      pointer-events: none;
    }
    .eyebrow {
      font-size: 12px;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 14px;
      font-weight: 700;
    }
    h1 {
      margin: 0 0 12px;
      font-size: 40px;
      line-height: 0.95;
      letter-spacing: -0.03em;
    }
    .lede {
      margin: 0 0 18px;
      color: var(--muted);
      line-height: 1.6;
      font-size: 15px;
    }
    .badge {
      display: inline-block;
      padding: 8px 12px;
      background: rgba(36, 75, 69, 0.08);
      color: var(--accent-2);
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
    }
    .panel { padding: 28px; }
    .toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }
    .title {
      font-size: 26px;
      margin: 0;
      letter-spacing: -0.03em;
    }
    .subtitle {
      color: var(--muted);
      margin: 6px 0 0;
      font-size: 14px;
    }
    form { display: grid; gap: 20px; }
    .section {
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.55);
    }
    .section h2 {
      margin: 0 0 14px;
      font-size: 16px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--accent-2);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .field {
      display: grid;
      gap: 8px;
    }
    .field.full { grid-column: 1 / -1; }
    label {
      font-size: 13px;
      font-weight: 700;
      color: var(--ink);
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
      color: var(--ink);
      background: #fff;
    }
    input:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 4px rgba(181, 71, 47, 0.12);
    }
    .checks {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      padding-top: 4px;
    }
    .check {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
      color: var(--muted);
    }
    .check input {
      width: 18px;
      height: 18px;
      accent-color: var(--accent);
    }
    .actions {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    button {
      border: none;
      border-radius: 14px;
      padding: 12px 18px;
      font: inherit;
      font-weight: 800;
      cursor: pointer;
      transition: transform 0.12s ease, opacity 0.12s ease;
    }
    button:hover { transform: translateY(-1px); }
    button.primary {
      background: var(--accent);
      color: #fff7f2;
    }
    button.secondary {
      background: rgba(36, 75, 69, 0.08);
      color: var(--accent-2);
    }
    .status {
      font-size: 14px;
      color: var(--muted);
      min-height: 22px;
    }
    .status.ok { color: var(--ok); font-weight: 700; }
    .status.warn { color: var(--accent); font-weight: 700; }
    .hint {
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .preview {
      margin-top: 12px;
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(36, 75, 69, 0.08);
      color: var(--accent-2);
      font-weight: 700;
      word-break: break-word;
    }
    .run-card {
      margin-top: 18px;
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.7);
    }
    .run-title {
      margin: 0 0 8px;
      font-size: 14px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent-2);
    }
    .run-body {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
      white-space: pre-line;
    }
    .task-list {
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 10px;
    }
    .task-item {
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.8);
      border: 1px solid var(--line);
    }
    .task-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 13px;
      margin-bottom: 6px;
    }
    .task-status {
      font-weight: 800;
      color: var(--accent-2);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .task-meta {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      word-break: break-word;
    }
    .task-actions {
      margin-top: 10px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .task-actions button {
      padding: 8px 12px;
      font-size: 12px;
      border-radius: 10px;
    }
    dialog.task-dialog {
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 0;
      width: min(760px, calc(100vw - 32px));
      box-shadow: var(--shadow);
    }
    dialog.task-dialog::backdrop {
      background: rgba(31, 36, 33, 0.35);
    }
    .dialog-shell {
      padding: 22px;
      background: var(--panel);
    }
    .dialog-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      margin-bottom: 12px;
    }
    .dialog-title {
      margin: 0;
      font-size: 20px;
      letter-spacing: -0.02em;
    }
    .dialog-grid {
      display: grid;
      gap: 10px;
    }
    .dialog-block {
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.8);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
      word-break: break-word;
      white-space: pre-line;
    }
    @media (max-width: 920px) {
      .shell { grid-template-columns: 1fr; }
      .hero { position: static; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="hero">
      <div class="eyebrow">mdcn 0.0.1</div>
      <h1>Config<br/>Studio</h1>
      <p class="lede">用一个本地网页把常用配置调顺，再交给命令行执行。适合先设置目录、命名规则、站点地址，再开始批量刮削。</p>
      <div class="badge" id="configPathBadge">loading config...</div>
    </aside>
    <main class="panel">
      <div class="toolbar">
        <div>
          <h1 class="title">项目设置</h1>
          <p class="subtitle">修改后会直接保存到当前 `config.toml`。</p>
        </div>
        <div class="actions">
          <button type="button" class="secondary" id="reloadButton">重新加载</button>
          <button type="button" class="secondary" id="retryFailedButton">保存并重跑失败任务</button>
          <button type="button" class="secondary" id="runButton">保存并开始刮削</button>
          <button type="submit" class="primary" form="configForm">保存配置</button>
        </div>
      </div>
      <form id="configForm">
        <section class="section">
          <h2>Paths</h2>
          <div class="grid">
            <div class="field full">
              <label for="source_dir">源目录</label>
              <input id="source_dir" name="source_dir" placeholder="/path/to/failed" />
            </div>
            <div class="field full">
              <label for="target_root">目标目录</label>
              <input id="target_root" name="target_root" placeholder="/path/to/library" />
            </div>
          </div>
        </section>

        <section class="section">
          <h2>Output</h2>
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
          <h2>Network</h2>
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
          <h2>Sites</h2>
          <div class="grid">
            <div class="field full">
              <label for="site_order">站点优先顺序</label>
              <input id="site_order" name="site_order" placeholder="avjia, tianmei, madouclub, madouqu, mdtv" />
              <div class="hint">按逗号分隔。刮削时会优先尝试前面的站点。</div>
            </div>
            <div class="field full">
              <label for="site_madouqu_base_url">MadouQu 地址</label>
              <input id="site_madouqu_base_url" name="site_madouqu_base_url" />
              <div class="hint">镜像地址用逗号分隔。</div>
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
              <div class="hint">适合 91 制片厂、天美、蜜桃、精东等国产站点元数据回查。</div>
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
        <section class="run-card">
          <h2 class="run-title">最近运行状态</h2>
          <div class="run-body" id="runStatusText">空闲</div>
        </section>
        <section class="run-card">
          <h2 class="run-title">最近任务</h2>
          <div class="run-body" id="taskSummaryText">暂无任务记录</div>
          <div class="actions" style="margin: 12px 0 10px;">
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
        </section>
      </form>
    </main>
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
      "site_order",
      "proxy", "timeout", "retries",
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
    const previewText = document.getElementById("previewText");
    const runStatusText = document.getElementById("runStatusText");
    const taskSummaryText = document.getElementById("taskSummaryText");
    const taskList = document.getElementById("taskList");
    const taskFilter = document.getElementById("taskFilter");
    const taskSearch = document.getElementById("taskSearch");
    const taskDetailDialog = document.getElementById("taskDetailDialog");
    const taskDetailTitle = document.getElementById("taskDetailTitle");
    const taskDetailGrid = document.getElementById("taskDetailGrid");

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

    function renderRunStatus(data) {
      if (!data) {
        runStatusText.textContent = "空闲";
        return;
      }

      const label = data.mode === "retry_failed" ? "失败任务重跑" : "刮削";
      const stats = data.last_stats ?? {};
      const lines = [
        data.running ? `${label} 正在运行` : `最近任务: ${label}`,
        `状态: ${data.message ?? "idle"}`,
        `开始时间: ${data.started_at || "-"}`,
        `结束时间: ${data.finished_at || "-"}`,
        `统计: scanned=${stats.scanned ?? 0} succeeded=${stats.succeeded ?? 0} failed=${stats.failed ?? 0} skipped=${stats.skipped ?? 0}`,
      ];
      if (data.last_error) {
        lines.push(`错误: ${data.last_error}`);
      }
      runStatusText.textContent = lines.join("\\n");
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
        const title = task.number || task.video_path || "unknown";
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
        if (task.status === "failed") {
          const actions = document.createElement("div");
          actions.className = "task-actions";
          const detailButton = document.createElement("button");
          detailButton.type = "button";
          detailButton.className = "secondary";
          detailButton.textContent = "查看详情";
          detailButton.addEventListener("click", () => openTaskDetail(task.video_path));
          const retryButton = document.createElement("button");
          retryButton.type = "button";
          retryButton.className = "secondary";
          retryButton.textContent = "重跑这条";
          retryButton.addEventListener("click", () => retrySingleTask(task.video_path));
          actions.appendChild(detailButton);
          actions.appendChild(retryButton);
          item.appendChild(actions);
        } else {
          const actions = document.createElement("div");
          actions.className = "task-actions";
          const detailButton = document.createElement("button");
          detailButton.type = "button";
          detailButton.className = "secondary";
          detailButton.textContent = "查看详情";
          detailButton.addEventListener("click", () => openTaskDetail(task.video_path));
          actions.appendChild(detailButton);
          item.appendChild(actions);
        }
        taskList.appendChild(item);
      }
    }

    async function refreshPreview() {
      const template = document.getElementById("folder_template").value || "{number} {title}";
      const response = await fetch(`/api/preview?template=${encodeURIComponent(template)}`);
      const data = await response.json();
      previewText.textContent = data.preview;
    }

    async function loadRunStatus() {
      const response = await fetch("/api/run-status");
      const data = await response.json();
      renderRunStatus(data);
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
        statusText.className = "status";
        return;
      }
      const task = data.task;
      taskDetailTitle.textContent = task.number || task.video_path || "任务详情";
      taskDetailGrid.innerHTML = "";
      const fields = [
        ["状态", task.status || "-"],
        ["更新时间", task.updated_at || "-"],
        ["源文件", task.video_path || "-"],
        ["输出目录", task.target_dir || "-"],
        ["来源站点", task.source || "-"],
        ["失败原因", task.reason || "-"],
        ["详情", task.detail || "-"],
      ];
      for (const [label, value] of fields) {
        const block = document.createElement("div");
        block.className = "dialog-block";
        block.textContent = `${label}: ${value}`;
        taskDetailGrid.appendChild(block);
      }
      taskDetailDialog.showModal();
    }

    async function loadConfig() {
      statusText.textContent = "正在读取配置...";
      const response = await fetch("/api/config");
      const data = await response.json();
      configPathBadge.textContent = data.config_path;
      document.getElementById("source_dir").value = data.source.dir ?? "";
      document.getElementById("target_root").value = data.target.root ?? "";
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
      await refreshPreview();
      await loadRunStatus();
      await loadTasks();
      statusText.textContent = "配置已加载。";
      statusText.className = "status";
    }

    async function saveConfig(event) {
      event.preventDefault();
      const payload = collectPayload();

      statusText.textContent = "正在保存...";
      statusText.className = "status";

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
      } else {
        statusText.textContent = "保存失败。";
        statusText.className = "status";
      }
    }

    async function saveAndRun(mode) {
      const payload = collectPayload();
      payload.mode = mode;

      statusText.textContent = mode === "retry_failed" ? "正在保存并启动失败任务重跑..." : "正在保存并启动刮削...";
      statusText.className = "status warn";

      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      renderRunStatus(result.status);
      await refreshPreview();
      await loadTasks();

      if (result.ok) {
        statusText.textContent = mode === "retry_failed" ? "已启动失败任务重跑。" : "已启动刮削任务。";
        statusText.className = "status ok";
      } else {
        statusText.textContent = result.error || "任务启动失败。";
        statusText.className = "status";
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
      renderRunStatus(result.status);
      await loadTasks();
      if (result.ok) {
        statusText.textContent = "已启动单条任务重跑。";
        statusText.className = "status ok";
      } else {
        statusText.textContent = result.error || "单条任务启动失败。";
        statusText.className = "status";
      }
    }

    document.getElementById("reloadButton").addEventListener("click", loadConfig);
    document.getElementById("reloadButtonBottom").addEventListener("click", loadConfig);
    document.getElementById("runButton").addEventListener("click", () => saveAndRun("scrape"));
    document.getElementById("runButtonBottom").addEventListener("click", () => saveAndRun("scrape"));
    document.getElementById("retryFailedButton").addEventListener("click", () => saveAndRun("retry_failed"));
    document.getElementById("retryFailedButtonBottom").addEventListener("click", () => saveAndRun("retry_failed"));
    document.getElementById("refreshTasksButton").addEventListener("click", loadTasks);
    taskFilter.addEventListener("change", loadTasks);
    taskSearch.addEventListener("input", loadTasks);
    document.getElementById("closeTaskDetailButton").addEventListener("click", () => taskDetailDialog.close());
    document.getElementById("folder_template").addEventListener("input", refreshPreview);
    form.addEventListener("submit", saveConfig);
    loadConfig();
    setInterval(async () => {
      await loadRunStatus();
      await loadTasks();
    }, 2000);
  </script>
</body>
</html>
"""
