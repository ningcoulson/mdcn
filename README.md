# mdcn

`mdcn` is a lightweight metadata scraper and organizer for Chinese original video libraries.
`mdcn` 是一个面向国产原创视频资料库的轻量元数据刮削与整理工具。

It is designed for local library workflows such as Emby, Jellyfin, and Kodi.
它面向本地媒体库场景，适合配合 Emby、Jellyfin、Kodi 使用。

## What It Does / 项目能做什么

- Scan a source folder and detect video files.
  扫描源目录并识别视频文件。
- Extract multiple number candidates from filenames.
  从文件名中提取多个番号候选。
- Search supported sites in configurable priority order.
  按可配置优先级搜索已支持站点。
- Parse title, number, actors, tags, images, release date, and related metadata.
  解析标题、番号、演员、标签、图片、发布日期等元数据。
- Download poster and extra fanart images.
  下载海报和额外剧照。
- Write `metadata.json` and `NFO`.
  写入 `metadata.json` 和 `NFO`。
- Move videos into clean library folders based on naming templates.
  根据命名模板把视频移动到整理后的资料库目录。
- Track task history in SQLite and retry failed jobs.
  使用 SQLite 记录任务历史，并支持失败任务重跑。
- Provide a local HTML control panel for configuration and task operations.
  提供本地 HTML 控制面板，用于配置和任务操作。

## Current Status / 当前状态

- Version / 版本: `0.0.1`
- Python / Python 要求: `3.11+`
- Interface / 使用方式:
  - CLI
  - local HTML config UI / 本地 HTML 配置页
- Storage / 任务记录:
  - `TARGET_ROOT/.mdcn/tasks.db`

## Supported Sites / 当前支持站点

| Site | Key | Status | Notes |
| --- | --- | --- | --- |
| MadouQu | `madouqu` | Stable | Search + detail parse + images |
| MadouTV | `mdtv` | Stable | Search + detail parse + images |
| MadouClub | `madouclub` | Available | Search + detail parse + images |
| AvJia | `avjia` | Available | Search + detail parse + images |

中文说明：

- `Stable` 表示当前测试覆盖更完整，适合日常使用。
- `Available` 表示已经接入并有测试，但后续仍会继续增强容错。

## Main Features / 主要特性

- Typed configuration with TOML.
  基于 TOML 的强类型配置。
- Configurable crawler priority.
  可配置站点优先顺序。
- Folder naming templates such as `{number} {title}` or `{studio}/{number} {title}`.
  支持 `{number} {title}`、`{studio}/{number} {title}` 这类目录命名模板。
- HTML config page with:
  HTML 配置页支持：
  - naming preview / 命名预览
  - save and scrape / 保存并开始刮削
  - retry failed jobs / 重跑失败任务
  - task summary / 任务汇总
  - recent task list / 最近任务列表
  - single-task retry for failed jobs / 单条失败任务重跑
- Test coverage for core parsers, config flow, task storage, and orchestration.
  为核心解析器、配置流程、任务存储和调度提供测试覆盖。

## Repository Layout / 目录结构

```text
src/mdcn/
  app/          CLI and local HTML control panel
  config/       TOML loading and typed config models
  crawlers/     Site-specific scrapers
  pipeline/     Orchestration, metadata, resources, writer, organizer
  storage/      SQLite task repository
  output/       Naming rules and output serialization
tests/
  fixtures/     HTML samples for parser tests
  unit/         Unit tests
  integration/  End-to-end pipeline tests
scripts/
  quickstart.sh       macOS/Linux quick start
  quickstart.command  double-click entry on macOS
  quickstart.bat      Windows quick start
```

## One-Click Quick Start / 一键快速启动

### macOS / Linux

```bash
./scripts/quickstart.sh
```

On macOS you can also double-click:
在 macOS 上也可以直接双击：

```text
scripts/quickstart.command
```

### Windows

Double-click or run:
双击或执行：

```bat
scripts\quickstart.bat
```

What the quick start script does / 一键脚本会做什么：

1. Create `.venv` if it does not exist.
   如果没有 `.venv` 就自动创建。
2. Install the project in editable mode.
   以可编辑模式安装项目。
3. Create `config.toml` from `config.example.toml` if missing.
   如果缺少 `config.toml`，自动从 `config.example.toml` 复制。
4. Launch the local HTML config UI.
   启动本地 HTML 配置页。

## Manual Setup / 手动安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp config.example.toml config.toml
```

Then run:
然后执行：

```bash
mdcn doctor --config config.toml
mdcn config-ui --config config.toml
```

## Typical Workflow / 典型使用流程

1. Open the HTML config page.
   打开 HTML 配置页。
2. Set source folder, target folder, naming rule, and site priority.
   设置源目录、目标目录、命名规则和站点优先级。
3. Click `保存并开始刮削`.
   点击“保存并开始刮削”。
4. Watch the task panel for success, failure, and retry actions.
   在任务面板里查看成功、失败和重跑状态。
5. If some files fail, use `保存并重跑失败任务` or retry a single task.
   如果有失败任务，使用“保存并重跑失败任务”或单条重跑。

## CLI Commands / 命令行命令

```bash
mdcn doctor --config config.toml
mdcn doctor --config config.toml --check-sites
mdcn scrape --config config.toml
mdcn retry-failed --config config.toml
mdcn tasks --config config.toml --status failed
mdcn config-ui --config config.toml
```

Command summary / 命令说明：

- `doctor`: print environment and configuration summary.
  Add `--check-sites` to probe site and mirror health.
  输出环境和配置摘要。
- `scrape`: scan the source directory and process files.
  扫描源目录并处理文件。
- `retry-failed`: retry tasks previously marked as failed.
  重跑之前标记为失败的任务。
- `tasks`: inspect recent task records, with status and keyword filters.
  查看最近任务记录，并支持状态和关键词筛选。
- `config-ui`: start the local HTML control panel.
  启动本地 HTML 控制面板。

## Configuration Highlights / 配置重点

Example:
示例：

```toml
[source]
dir = "/path/to/failed"

[target]
root = "/path/to/library"

[output]
folder_template = "{studio}/{number} {title}"

[priority]
site_order = ["madouqu", "mdtv", "madouclub", "avjia"]

[sites.avjia]
base_url = "https://avjia.net"
mirrors = ["https://mirror.avjia.net"]
```

Useful naming placeholders / 可用命名占位符：

- `{number}`
- `{title}`
- `{studio}`
- `{series}`
- `{source}`
- `{year}`
- `{actors}`

## Output Example / 输出示例

```text
Library/
  Madou/
    MD-001 Sample Title/
      MD001.mp4
      MD-001.nfo
      metadata.json
      MD-001_poster.jpg
      MD-001_extrafanart_2.jpg
```

## Task Panel / 任务面板

The HTML task panel currently supports:
当前 HTML 任务面板支持：

- recent run summary / 最近运行摘要
- recent task list / 最近任务列表
- status filter / 状态筛选
- keyword search / 关键词搜索
- failed-task retry / 失败任务整批重跑
- single failed task retry / 单条失败任务重跑
- task detail dialog / 任务详情弹窗
- task details including source path, target path, source site, and failure detail
  任务详情，包括源文件路径、目标目录、来源站点和失败信息

## Development / 开发与测试

Run all tests:
运行全部测试：

```bash
PYTHONPATH=src python3 -m pytest -q
```

The current project includes parser fixtures and pipeline tests for the implemented sites.
当前项目已经为已实现站点提供了解析 fixture 和 pipeline 测试。

## Notes / 说明

- `mdcn` focuses on metadata scraping and local library organization.
  `mdcn` 专注于元数据刮削和本地资料库整理。
- It does not provide video downloading.
  它不提供视频下载能力。
- Site structure can change over time; crawler fixes will continue in follow-up releases.
  站点结构会变化，crawler 的兼容修复会在后续版本持续推进。

## Documentation / 进一步文档

- [docs/development_plan.md](docs/development_plan.md)
- [docs/getting_started.md](docs/getting_started.md)
- [docs/architecture.md](docs/architecture.md)
