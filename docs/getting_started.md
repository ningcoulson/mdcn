# Getting Started

## What mdcn Does

`mdcn` scans a folder of local video files, extracts number candidates from filenames, queries supported websites for metadata, downloads poster and fanart images, writes `metadata.json` and `NFO`, and then moves the video into a clean library folder.

Version `0.0.1` is the first usable CLI-oriented build.

## Requirements

- macOS, Linux, or Windows
- Python 3.11 or newer
- internet access to the target sites

## Install

### Fastest Start

If you want the shortest path and are on macOS or Linux:

```bash
./scripts/quickstart.sh
```

This will:

- create `.venv`
- install `mdcn`
- create `config.toml` if missing
- launch the local HTML config UI

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install the project

```bash
pip install -e .[dev]
```

## Configure

Copy `config.example.toml` to `config.toml` and edit the paths:

```toml
[source]
dir = "/path/to/failed"

[target]
root = "/path/to/library"
```

## Run Diagnostics

```bash
mdcn doctor --config config.toml
```

To probe site and mirror health:

```bash
mdcn doctor --config config.toml --check-sites
```

This prints:

- mdcn version
- Python version
- source path
- target path
- enabled sites

## Run a Scrape

```bash
mdcn scrape --config config.toml
```

## Retry Only Failed Files

If some files failed in a previous run and still exist on disk, retry only those tasks:

```bash
mdcn retry-failed --config config.toml
```

## Inspect Task History

Use the CLI if you want a quick terminal view of recent records:

```bash
mdcn tasks --config config.toml --status failed
```

## Use the HTML Config Page

If you prefer editing settings in a browser instead of hand-writing TOML, start the local config UI:

```bash
mdcn config-ui --config config.toml
```

Then open the printed local URL if your browser does not open automatically.

The page currently supports:

- source folder
- target folder
- naming rule
- naming rule preview
- site priority order
- max image count
- proxy, timeout, retries
- video extensions
- site enable switches
- site base URLs
- save and start scrape
- save and retry failed tasks
- recent run status
- recent task list

After clicking save, the page writes directly back to `config.toml`.

Naming templates support these placeholders:

- `{number}`
- `{title}`
- `{studio}`
- `{series}`
- `{source}`
- `{year}`
- `{actors}`

Example templates:

- `{number} {title}`
- `{studio}/{number} {title}`
- `{year}/{number} {title}`

Crawler priority example:

- `madouqu, mdtv`
- `mdtv, madouqu`

When a file is matched successfully, mdcn will:

1. create a target folder like `{number} {title}`
2. download poster and fanart
3. write `metadata.json`
4. write `NFO`
5. move the source video into the target folder
6. record task history in `TARGET_ROOT/.mdcn/tasks.db`

## Output Example

```text
Library/
  MD-001 Sample Title/
    MD001.mp4
    MD-001.nfo
    metadata.json
    MD-001_poster.jpg
```

## Current Supported Sites

- `madouqu`
- `mdtv`
- `madouclub`
- `avjia`

More sites can be added without changing the rest of the pipeline because each crawler is isolated behind the shared crawler interface.
