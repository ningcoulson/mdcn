"""Lightweight local HTML config UI."""

from __future__ import annotations

import json
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mdcn.config import AppConfig, PathsConfig, build_config_from_dict, config_to_dict, load_config, save_config


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
    handler = _make_handler(config_path)
    return ThreadingHTTPServer((host, port), handler)


def _make_handler(config_path: Path):
    class ConfigUIHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send_html(render_config_ui_html())
                return
            if self.path == "/api/config":
                _ensure_config_exists(config_path)
                config = load_config(config_path)
                payload = config_to_dict(config)
                payload["config_path"] = str(config_path)
                self._send_json(payload)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/config":
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw_body)
            config = build_config_from_ui_payload(payload)
            save_config(config, config_path)
            self._send_json({"ok": True, "config_path": str(config_path)})

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_html(self, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
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
        "sites": {
            "madouqu": {
                "enabled": bool(payload.get("site_madouqu_enabled", True)),
                "base_url": str(payload.get("site_madouqu_base_url", "")).strip(),
            },
            "mdtv": {
                "enabled": bool(payload.get("site_mdtv_enabled", True)),
                "base_url": str(payload.get("site_mdtv_base_url", "")).strip(),
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
              <label for="site_madouqu_base_url">MadouQu 地址</label>
              <input id="site_madouqu_base_url" name="site_madouqu_base_url" />
            </div>
            <div class="field full">
              <label for="site_mdtv_base_url">MadouTV 地址</label>
              <input id="site_mdtv_base_url" name="site_mdtv_base_url" />
            </div>
          </div>
          <div class="checks">
            <label class="check"><input id="site_madouqu_enabled" name="site_madouqu_enabled" type="checkbox" /> 启用 MadouQu</label>
            <label class="check"><input id="site_mdtv_enabled" name="site_mdtv_enabled" type="checkbox" /> 启用 MadouTV</label>
          </div>
        </section>

        <div class="actions">
          <button type="button" class="secondary" id="reloadButtonBottom">重新加载</button>
          <button type="submit" class="primary">保存配置</button>
          <div class="status" id="statusText"></div>
        </div>
      </form>
    </main>
  </div>

  <script>
    const fields = [
      "source_dir", "target_root", "folder_template", "max_images", "extensions",
      "proxy", "timeout", "retries",
      "site_madouqu_base_url", "site_mdtv_base_url"
    ];
    const checks = [
      "write_nfo", "write_json", "site_madouqu_enabled", "site_mdtv_enabled"
    ];

    const form = document.getElementById("configForm");
    const statusText = document.getElementById("statusText");
    const configPathBadge = document.getElementById("configPathBadge");

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
      document.getElementById("proxy").value = data.network.proxy ?? "";
      document.getElementById("timeout").value = data.network.timeout ?? 20;
      document.getElementById("retries").value = data.network.retries ?? 2;
      document.getElementById("write_nfo").checked = Boolean(data.output.write_nfo);
      document.getElementById("write_json").checked = Boolean(data.output.write_json);
      document.getElementById("site_madouqu_enabled").checked = Boolean(data.sites.madouqu?.enabled);
      document.getElementById("site_mdtv_enabled").checked = Boolean(data.sites.mdtv?.enabled);
      document.getElementById("site_madouqu_base_url").value = data.sites.madouqu?.base_url ?? "";
      document.getElementById("site_mdtv_base_url").value = data.sites.mdtv?.base_url ?? "";
      statusText.textContent = "配置已加载。";
      statusText.className = "status";
    }

    async function saveConfig(event) {
      event.preventDefault();
      const payload = {};
      for (const name of fields) {
        payload[name] = document.getElementById(name).value;
      }
      for (const name of checks) {
        payload[name] = document.getElementById(name).checked;
      }

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
      } else {
        statusText.textContent = "保存失败。";
        statusText.className = "status";
      }
    }

    document.getElementById("reloadButton").addEventListener("click", loadConfig);
    document.getElementById("reloadButtonBottom").addEventListener("click", loadConfig);
    form.addEventListener("submit", saveConfig);
    loadConfig();
  </script>
</body>
</html>
"""
