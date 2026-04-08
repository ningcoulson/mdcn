"""CLI entrypoint placeholder."""

from __future__ import annotations

import argparse
import asyncio
import platform
from pathlib import Path

from mdcn2 import __version__
from mdcn2.app.bootstrap import build_orchestrator
from mdcn2.config.loader import load_config


def _default_config_path() -> str:
    return str(Path("config.toml"))

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mdcn2", description="Metadata scraper toolkit for Chinese original video workflows")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser("scrape", help="Scan the source directory and process video files")
    scrape.add_argument("--config", help="Path to config TOML file", default=_default_config_path())

    doctor = subparsers.add_parser("doctor", help="Print environment and config diagnostics")
    doctor.add_argument("--config", help="Path to config TOML file", default=_default_config_path())
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "doctor":
        print(f"mdcn2 version: {__version__}")
        print(f"python: {platform.python_version()}")
        print(f"source: {config.paths.source_dir}")
        print(f"target: {config.paths.target_root}")
        print(f"sites: {', '.join(sorted(config.sites)) or 'default'}")
        return 0

    if args.command == "scrape":
        stats = asyncio.run(build_orchestrator(config).run())
        print(f"scanned={stats.scanned} succeeded={stats.succeeded} failed={stats.failed} skipped={stats.skipped}")
        return 0

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
