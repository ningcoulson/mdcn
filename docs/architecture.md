# Architecture

## Overview

`mdcn2` is split into small modules so that scraper logic, file operations, and persistence do not get tangled together.

## Module Map

### `domain`

Shared data types and error classes.

Examples:

- `VideoFile`
- `NumberCandidate`
- `MetadataResult`

### `config`

Loads TOML configuration into typed dataclasses.

### `scanner`

Scans source directories and extracts number candidates from filenames.

### `crawlers`

Each site implementation inherits from `BaseCrawler` and only handles:

- search
- fetch
- parse

### `pipeline`

Coordinates the work after a crawler returns metadata:

- normalize metadata
- download resources
- write output files
- organize the target folder

### `storage`

Persists task history in SQLite for retries and reporting.

### `app`

Provides CLI wiring and bootstraps the orchestrator.

## Processing Flow

1. CLI loads `config.toml`
2. scanner finds candidate video files
3. filename parser extracts number candidates
4. orchestrator tries enabled crawlers in order
5. metadata is normalized
6. images are downloaded
7. `metadata.json` and `NFO` are written
8. video file is moved
9. task result is written into SQLite

## Why This Split Matters

This layout makes it easier to:

- add new sites without rewriting file-handling code
- test crawlers with HTML fixtures
- test the orchestration flow with fake crawlers
- retry failures later from recorded task state
