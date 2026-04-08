"""Shared enums."""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class FailureReason(StrEnum):
    NO_CANDIDATE = "no_candidate"
    NO_MATCH = "no_match"
    NETWORK = "network"
    PARSE = "parse"
    DOWNLOAD = "download"
    WRITE = "write"
