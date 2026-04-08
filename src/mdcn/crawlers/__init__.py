"""Crawler abstractions and implementations."""

from .avjia import AvJiaCrawler
from .base import BaseCrawler
from .madouclub import MadouClubCrawler
from .madouqu import MadouQuCrawler
from .mdtv import MadouTVCrawler
from .registry import CrawlerRegistry

__all__ = [
    "AvJiaCrawler",
    "BaseCrawler",
    "CrawlerRegistry",
    "MadouClubCrawler",
    "MadouQuCrawler",
    "MadouTVCrawler",
]
