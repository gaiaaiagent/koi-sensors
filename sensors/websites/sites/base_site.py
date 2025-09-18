"""
Base class for site-specific handlers
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List
from bs4 import BeautifulSoup
import logging
import re


class BaseSite(ABC):
    """Base class for site-specific content extraction"""

    def __init__(self, domain: str, logger: logging.Logger):
        self.domain = domain
        self.logger = logger

    @abstractmethod
    def extract_publication_date(self, soup: BeautifulSoup, url: str) -> Tuple[Optional[datetime], float]:
        """
        Extract publication date from the page

        Returns:
            Tuple of (datetime or None, confidence score 0.0-1.0)
        """
        pass

    @abstractmethod
    def should_extract_content(self, url: str) -> bool:
        """
        Determine if this URL should have its content extracted

        Some pages (like index pages) might not need content extraction
        """
        pass

    @abstractmethod
    def extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """
        Extract site-specific metadata from the page

        Returns dictionary with metadata fields specific to this site
        """
        pass

    def get_links_to_follow(self, soup: BeautifulSoup, url: str) -> List[str]:
        """
        Get list of links from this page that should be followed

        Override this to implement custom crawling logic
        (e.g., only follow links to meeting pages on regentokenomics)
        """
        links = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            # Convert relative URLs to absolute
            if href.startswith('/'):
                href = f"https://{self.domain}{href}"
            elif not href.startswith(('http://', 'https://')):
                continue

            # Only follow links on same domain
            if self.domain in href:
                links.append(href)

        return links

    def extract_content_text(self, soup: BeautifulSoup, url: str) -> str:
        """
        Extract the main content text from the page

        Override for custom content extraction
        """
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()

        # Get text
        text = soup.get_text()

        # Break into lines and remove leading/trailing space
        lines = (line.strip() for line in text.splitlines())
        # Break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # Drop blank lines
        text = '\n'.join(chunk for chunk in chunks if chunk)

        return text

    def identify_content_type(self, soup: BeautifulSoup, url: str) -> str:
        """
        Identify the type of content on this page

        Returns a string like 'article', 'meeting', 'index', 'documentation', etc.
        """
        # Default implementation - can be overridden
        if '/meeting' in url or '/weekly-meetup' in url:
            return 'meeting'
        elif '/blog' in url or '/article' in url:
            return 'article'
        elif any(x in url for x in ['/docs', '/guide', '/documentation']):
            return 'documentation'
        elif url.endswith('/') or '/index' in url:
            return 'index'
        else:
            return 'page'