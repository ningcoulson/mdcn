# mdcn

`mdcn` is a clean-room rewrite of the current `mdcn` workflow, focused on:

- stable batch scraping for Chinese original video sites
- modular crawler boundaries
- testable pipelines
- resumable task execution

## Version

Current release target: `0.0.1`

## What Works In 0.0.1

- TOML-based configuration
- CLI commands: `doctor` and `scrape`
- typed domain/config models
- filename scanning and number extraction
- crawler base and registry
- `MadouQu` crawler
- `MadouTV` crawler
- metadata normalization
- image download pipeline
- `metadata.json` and `NFO` output
- file organization
- SQLite task tracking
- unit and integration tests

## Workflow

1. Scan a source directory for video files.
2. Extract multiple number candidates from each filename.
3. Try configured crawlers in order.
4. Normalize metadata.
5. Download poster and extrafanart, or fallback to frame extraction.
6. Write `metadata.json` and `NFO`.
7. Move the video into a structured target directory.
8. Record the task result for retries and reporting.

## Quick Start

1. Copy `config.example.toml` to `config.toml`.
2. Edit the source and target paths.
3. Install the package:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

4. Check the environment:

```bash
mdcn doctor --config config.toml
```

5. Run a scrape:

```bash
mdcn scrape --config config.toml
```

## Documentation

See [docs/development_plan.md](docs/development_plan.md) for the current implementation plan.
See [docs/getting_started.md](docs/getting_started.md) for end-user setup instructions.
See [docs/architecture.md](docs/architecture.md) for the module layout.
