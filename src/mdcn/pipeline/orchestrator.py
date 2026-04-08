"""High-level scrape orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mdcn.config.models import AppConfig
from mdcn.crawlers.registry import CrawlerRegistry
from mdcn.domain.enums import FailureReason
from mdcn.domain.models import MetadataResult, NumberCandidate, VideoFile
from mdcn.pipeline.metadata import MetadataPipeline
from mdcn.pipeline.organizer import FileOrganizer
from mdcn.pipeline.resources import ResourcePipeline
from mdcn.pipeline.writer import OutputWriter
from mdcn.scanner.files import iter_video_files
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
    ) -> None:
        self.config = config
        self.registry = registry
        self.metadata_pipeline = metadata_pipeline
        self.resource_pipeline = resource_pipeline
        self.writer = writer
        self.organizer = organizer
        self.task_repo = task_repo

    async def run(self) -> RunStats:
        files = iter_video_files(self.config.paths.source_dir, self.config.scanner.normalized_extensions())
        stats = RunStats(scanned=len(files))
        for video in files:
            outcome = await self.process_video(video)
            setattr(stats, outcome, getattr(stats, outcome) + 1)
        return stats

    async def process_video(self, video: VideoFile) -> str:
        video_path = str(video.path)
        if self.task_repo.was_processed(video_path):
            return "skipped"

        self.task_repo.start_task(video_path)
        candidates = extract_candidates(video.stem)
        if not candidates:
            self.task_repo.mark_failure(video_path, reason=FailureReason.NO_CANDIDATE.value)
            return "failed"

        for crawler in self.registry.get_enabled(self.config.sites):
            for candidate in candidates:
                try:
                    result = await crawler.run(candidate, file_hint=video.path.name)
                    await self._handle_success(video, candidate, result)
                    return "succeeded"
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    continue

        self.task_repo.mark_failure(
            video_path,
            reason=FailureReason.NO_MATCH.value,
            detail=str(last_error) if "last_error" in locals() else "",
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
        self.organizer.move_video(video.path, target_dir)
        self.task_repo.mark_success(
            str(video.path),
            source=normalized.source,
            number=normalized.number or candidate.normalized,
            target_dir=str(target_dir),
        )
