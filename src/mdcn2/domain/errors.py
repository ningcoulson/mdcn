"""Shared exceptions."""

from __future__ import annotations


class Mdcn2Error(RuntimeError):
    """Base project error."""


class ConfigError(Mdcn2Error):
    """Raised when configuration is missing or invalid."""


class NetworkError(Mdcn2Error):
    """Raised when a network request fails."""


class SearchError(Mdcn2Error):
    """Raised when a crawler cannot find a matching detail page."""


class ParseError(Mdcn2Error):
    """Raised when parsing structured content fails."""


class CrawlMismatchError(ParseError):
    """Raised when a crawler finds a page that does not match the expected number."""
