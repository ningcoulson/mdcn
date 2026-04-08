"""CLI entrypoint placeholder."""

from __future__ import annotations

import argparse
import asyncio
import platform
from pathlib import Path

from mdcn import __version__
from mdcn.app.bootstrap import build_crawlers, build_orchestrator
from mdcn.app.config_ui import serve_config_ui
from mdcn.config.loader import load_config
from mdcn.storage.task_repo import TaskRepository


def _default_config_path() -> str:
    return str(Path("config.toml"))

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mdcn", description="Metadata scraper toolkit for Chinese original video workflows")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser("scrape", help="Scan the source directory and process video files")
    scrape.add_argument("--config", help="Path to config TOML file", default=_default_config_path())

    retry_failed = subparsers.add_parser("retry-failed", help="Retry files that previously failed in the task database")
    retry_failed.add_argument("--config", help="Path to config TOML file", default=_default_config_path())

    tasks = subparsers.add_parser("tasks", help="List recent task records from the task database")
    tasks.add_argument("--config", help="Path to config TOML file", default=_default_config_path())
    tasks.add_argument("--status", help="Filter by status", default="all")
    tasks.add_argument("--query", help="Filter by keyword", default="")
    tasks.add_argument("--limit", help="Maximum number of tasks", type=int, default=20)

    doctor = subparsers.add_parser("doctor", help="Print environment and config diagnostics")
    doctor.add_argument("--config", help="Path to config TOML file", default=_default_config_path())
    doctor.add_argument("--check-sites", help="Probe site health and mirror availability", action="store_true")

    config_ui = subparsers.add_parser("config-ui", help="Open a local HTML interface for editing config.toml")
    config_ui.add_argument("--config", help="Path to config TOML file", default=_default_config_path())
    config_ui.add_argument("--host", help="Host to bind", default="127.0.0.1")
    config_ui.add_argument("--port", help="Port to bind", type=int, default=8765)
    config_ui.add_argument("--no-browser", help="Do not auto-open a browser tab", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "doctor":
        config = load_config(args.config)
        print(f"mdcn version: {__version__}")
        print(f"python: {platform.python_version()}")
        print(f"source: {config.paths.source_dir}")
        print(f"target: {config.paths.target_root}")
        print(f"sites: {', '.join(sorted(config.sites)) or 'default'}")
        if args.check_sites:
            asyncio.run(_print_site_health(config))
        return 0

    if args.command == "scrape":
        config = load_config(args.config)
        stats = asyncio.run(build_orchestrator(config).run())
        print(f"scanned={stats.scanned} succeeded={stats.succeeded} failed={stats.failed} skipped={stats.skipped}")
        return 0

    if args.command == "retry-failed":
        config = load_config(args.config)
        stats = asyncio.run(build_orchestrator(config).retry_failed())
        print(f"scanned={stats.scanned} succeeded={stats.succeeded} failed={stats.failed} skipped={stats.skipped}")
        return 0

    if args.command == "tasks":
        config = load_config(args.config)
        repo = TaskRepository(config.paths.target_root / ".mdcn" / "tasks.db")
        tasks = repo.list_recent_tasks(limit=args.limit, status=args.status, query=args.query or None)
        if not tasks:
            print("no task records found")
            return 0
        for task in tasks:
            summary = task["number"] or task["video_path"]
            extra = task["detail"] or task["target_dir"] or task["source"] or "-"
            print(f"[{task['status']}] {summary}")
            print(f"  updated: {task['updated_at']}")
            print(f"  path: {task['video_path']}")
            print(f"  info: {extra}")
        return 0

    if args.command == "config-ui":
        print(f"mdcn config UI listening at http://{args.host}:{args.port}")
        try:
            serve_config_ui(
                config_path=args.config,
                host=args.host,
                port=args.port,
                open_browser=not args.no_browser,
            )
        except KeyboardInterrupt:
            print("\nmdcn config UI stopped.")
        return 0

    return 0


async def _print_site_health(config) -> None:
    print("site health:")
    for crawler in build_crawlers(config):
        candidate_urls = crawler.candidate_base_urls()
        statuses = []
        for url in candidate_urls:
            ok = await crawler.check_health(url)
            statuses.append(f"{url}={'ok' if ok else 'down'}")
        await crawler.resolve_base_url()
        print(f"  {crawler.name}: selected={crawler.base_url}")
        print(f"    mirrors: {', '.join(statuses)}")
        await crawler.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
