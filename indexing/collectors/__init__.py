"""
Document collectors for various data sources
"""

from .base_collector import BaseCollector, Document, BatchCollector
from .git_collector import GitCollector
from .discourse_collector import DiscourseCollector
from .web_scraper import WebScraper

__all__ = [
    'BaseCollector',
    'Document', 
    'BatchCollector',
    'GitCollector',
    'DiscourseCollector',
    'WebScraper'
]