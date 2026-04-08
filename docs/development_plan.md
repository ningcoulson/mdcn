# mdcn2 Development Plan

## Goals

- Build a maintainable rewrite of the existing `mdcn` workflow.
- Keep the current business value: scan, match, scrape, download, write metadata, organize files.
- Improve module boundaries, failure handling, and test coverage from day one.

## MVP Scope

The MVP must support:

1. directory scanning
2. filename-to-number candidate extraction
3. crawler abstraction and registry
4. metadata normalization
5. image download with optional video frame fallback
6. NFO and JSON output
7. file organization
8. SQLite-backed task records
9. a CLI entrypoint

The MVP will not include:

- Web UI
- desktop GUI
- advanced plugin marketplace
- media-server sync
- actor encyclopedia enrichment

## Module Order

The codebase is being built in this order:

1. `domain`
2. `config`
3. `scanner`
4. `output`
5. `crawlers`
6. `pipeline`
7. `storage`
8. `app`

This ordering keeps low-level types and pure functions stable before the IO-heavy layers are added.

## Initial Deliverables

### Phase 1

- package scaffold
- project metadata
- base docs
- unit tests for pure helpers

### Phase 2

- `BaseCrawler`
- `CrawlerRegistry`
- first crawler implementation
- fixture-based crawler tests

### Phase 3

- metadata pipeline
- output writer
- file organizer
- resource pipeline

### Phase 4

- SQLite task repository
- orchestrator
- CLI
- end-to-end integration tests

## Testing Strategy

### Unit tests

Cover pure modules:

- filename parsing
- number normalization
- naming rules
- NFO generation
- config loading

### Fixture tests

Each crawler should have:

- one search fixture
- one detail fixture
- one success test
- one mismatch rejection test

### Integration tests

The integration suite should validate:

- successful scrape from local file to output directory
- failure recording when all crawlers miss
- image download fallback path

## Constraints

- Prefer standard library unless a dependency clearly pays for itself.
- Keep network logic isolated in shared client helpers.
- Keep crawlers responsible only for search/fetch/parse.
- Keep file movement, output generation, and task storage outside crawler modules.

## Definition of Done for Each Module

- module has a clear responsibility
- public APIs are typed
- at least one test covers expected behavior
- failures are explicit and readable

## Current Progress

Completed:

- repository skeleton
- phase 1 documentation
- domain/config/scanner/output core modules
- unit tests for first-pass modules

Next up:

- crawler base and registry
- first crawler migration
- orchestrator shell
