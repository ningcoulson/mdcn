"""Crawler abstractions and implementations."""

from .base import BaseCrawler
from .madouqu import MadouQuCrawler
from .mdtv import MadouTVCrawler
from .registry import CrawlerRegistry

__all__ = ["BaseCrawler", "CrawlerRegistry", "MadouQuCrawler", "MadouTVCrawler"]
