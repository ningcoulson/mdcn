"""High-level scrape orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from mdcn.config.models import AppConfig
from mdcn.crawlers.registry import CrawlerRegistry
from mdcn.domain.enums import FailureReason
from mdcn.domain.models import MetadataResult, NumberCandidate, VideoFile
from mdcn.pipeline.metadata import MetadataPipeline
from mdcn.pipeline.organizer import FileOrganizer
from mdcn.pipeline.resources import ResourcePipeline
from mdcn.pipeline.writer import OutputWriter
from mdcn.scanner.files import build_video_file, iter_video_files
from mdcn.scanner.number_parser import extract_candidates
from mdcn.storage.task_repo import TaskRepository


@dataclass(slots=True)
class RunStats:
    scanned: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


class ScrapeOrchestrator:
    def __init__(
        self,
        *,
        config: AppConfig,
        registry: CrawlerRegistry,
        metadata_pipeline: MetadataPipeline,
        resource_pipeline: ResourcePipeline,
        writer: OutputWriter,
        organizer: FileOrganizer,
        task_repo: TaskRepository,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.metadata_pipeline = metadata_pipeline
        self.resource_pipeline = resource_pipeline
        self.writer = writer
        self.organizer = organizer
        self.task_repo = task_repo
        self.progress_callback = progress_callback

    async def run(self, files: list[VideoFile] | None = None) -> RunStats:
        if files is None:
            files = iter_video_files(self.config.paths.source_dir, self.config.scanner.normalized_extensions())
        stats = RunStats(scanned=len(files))
        self._emit_progress({"event": "run_started", "total": len(files), "stats": self._stats_payload(stats)})
        for video in files:
            outcome = await self.process_video(video)
            setattr(stats, outcome, getattr(stats, outcome) + 1)
            self._emit_progress(
                {
                    "event": "video_finished",
                    "video_path": str(video.path),
                    "outcome": outcome,
                    "stats": self._stats_payload(stats),
                    "total": stats.scanned,
                }
            )
        self._emit_progress({"event": "run_finished", "total": stats.scanned, "stats": self._stats_payload(stats)})
        return stats

    async def retry_failed(self) -> RunStats:
        return await self.retry_video_paths(self.task_repo.list_failed_video_paths())

    async def retry_video_paths(self, video_paths: list[str]) -> RunStats:
        stats = RunStats()
        for video_path in video_paths:
            path = Path(video_path)
            if not path.exists() or not path.is_file():
                stats.skipped += 1
                continue
            if path.suffix.lower() not in self.config.scanner.normalized_extensions():
                stats.skipped += 1
                continue
            stats.scanned += 1
            outcome = await self.process_video(build_video_file(path))
            setattr(stats, outcome, getattr(stats, outcome) + 1)
        return stats

    async def process_video(self, video: VideoFile) -> str:
        video_path = str(video.path)
        if self.task_repo.was_processed(video_path):
            self._emit_progress({"event": "video_started", "video_path": video_path, "state": "skipped_existing"})
            return "skipped"

        self.task_repo.start_task(video_path)
        candidates = extract_candidates(video.stem)
        self._emit_progress(
            {
                "event": "video_started",
                "video_path": video_path,
                "label": video.path.name,
                "candidates": [candidate.normalized for candidate in candidates],
            }
        )
        if not candidates:
            self.task_repo.mark_failure(video_path, reason=FailureReason.NO_CANDIDATE.value)
            return "failed"

        attempts: list[str] = []
        last_error: Exception | None = None
        for crawler in self.registry.get_enabled(self.config.sites, self.config.priority.site_order):
            for candidate in candidates:
                self._emit_progress(
                    {
                        "event": "candidate_try",
                        "video_path": video_path,
                        "crawler": crawler.name,
                        "candidate": candidate.normalized,
                    }
                )
                try:
                    result = await crawler.run(candidate, file_hint=video.path.name)
                    await self._handle_success(video, candidate, result)
                    return "succeeded"
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    attempts.append(f"{crawler.name}:{candidate.normalized}:{type(exc).__name__}")
                    self._emit_progress(
                        {
                            "event": "candidate_miss",
                            "video_path": video_path,
                            "crawler": crawler.name,
                            "candidate": candidate.normalized,
                            "error_type": type(exc).__name__,
                        }
                    )
                    continue

        self.task_repo.mark_failure(
            video_path,
            reason=FailureReason.NO_MATCH.value,
            detail=self._build_failure_detail(attempts, last_error),
        )
        return "failed"

    async def _handle_success(
        self,
        video: VideoFile,
        candidate: NumberCandidate,
        result: MetadataResult,
    ) -> None:
        normalized = self.metadata_pipeline.normalize(result)
        target_dir = self.organizer.build_target_dir(normalized, self.config.paths.target_root)
        await self.resource_pipeline.process(normalized, target_dir)
        if self.config.output.write_json:
            self.writer.write_metadata_json(normalized, target_dir)
        if self.config.output.write_nfo:
            self.writer.write_nfo(normalized, target_dir)
        self.organizer.move_video(video.path, target_dir, normalized)
        poster_path = ""
        for image in normalized.images:
            if image.kind == "poster" and image.local_path is not None:
                poster_path = str(image.local_path)
                break
        if not poster_path:
            for image in normalized.images:
                if image.local_path is not None:
                    poster_path = str(image.local_path)
                    break
        self.task_repo.mark_success(
            str(video.path),
            source=normalized.source,
            number=normalized.number or candidate.normalized,
            title=normalized.title,
            target_dir=str(target_dir),
            poster_path=poster_path,
        )
        self._emit_progress(
            {
                "event": "video_succeeded",
                "video_path": str(video.path),
                "number": normalized.number or candidate.normalized,
                "title": normalized.title,
                "source": normalized.source,
                "target_dir": str(target_dir),
                "poster_path": poster_path,
            }
        )

    def _build_failure_detail(self, attempts: list[str], last_error: Exception | None) -> str:
        parts: list[str] = []
        if attempts:
            parts.append("attempts=" + ", ".join(attempts))
        if last_error is not None:
            parts.append(f"last_error={last_error}")
        return " | ".join(parts)

    def _stats_payload(self, stats: RunStats) -> dict[str, int]:
        return {
            "scanned": stats.scanned,
            "succeeded": stats.succeeded,
            "failed": stats.failed,
            "skipped": stats.skipped,
        }

    def _emit_progress(self, payload: dict[str, Any]) -> None:
        if self.progress_callback is None:
            return
        self.progress_callback(payload)
