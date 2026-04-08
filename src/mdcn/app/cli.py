"""CLI entrypoint placeholder."""

from __future__ import annotations

import argparse
import asyncio
import platform
from pathlib import Path

from mdcn import __version__
from mdcn.app.bootstrap import build_orchestrator
from mdcn.app.config_ui import serve_config_ui
from mdcn.config.loader import load_config


def _default_config_path() -> str:
    return str(Path("config.toml"))

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mdcn", description="Metadata scraper toolkit for Chinese original video workflows")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser("scrape", help="Scan the source directory and process video files")
    scrape.add_argument("--config", help="Path to config TOML file", default=_default_config_path())

    doctor = subparsers.add_parser("doctor", help="Print environment and config diagnostics")
    doctor.add_argument("--config", help="Path to config TOML file", default=_default_config_path())

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
        return 0

    if args.command == "scrape":
        config = load_config(args.config)
        stats = asyncio.run(build_orchestrator(config).run())
        print(f"scanned={stats.scanned} succeeded={stats.succeeded} failed={stats.failed} skipped={stats.skipped}")
        return 0

    if args.command == "config-ui":
        print(f"mdcn config UI listening at http://{args.host}:{args.port}")
        serve_config_ui(
            config_path=args.config,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
        return 0

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
