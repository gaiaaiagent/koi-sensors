"""
KOI Sensor Network - Web Content RID Types
Resource Identifiers for websites, discourse forums, and web pages
"""

import hashlib
from typing import Optional
from rid_lib.core import ORN


class WebPage(ORN):
    """Web page resource identifier
    Format: orn:web.page:domain/path_hash

    Uses SHA-256 hash of full URL path to handle long URLs while maintaining uniqueness
    """
    namespace = "web.page"

    def __init__(self, domain: str, full_url: str):
        self.domain = domain
        self.full_url = full_url
        # Create hash of full URL path for uniqueness
        self.path_hash = hashlib.sha256(full_url.encode('utf-8')).hexdigest()[:16]
        self._reference = f"{domain}/{self.path_hash}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid WebPage reference: {reference}")
        # We can't recover the full URL from the hash, so we'll use a placeholder
        return cls(parts[0], f"https://{parts[0]}/unknown")

    @property
    def reference(self) -> str:
        return self._reference


class WebSite(ORN):
    """Website resource identifier
    Format: orn:web.site:domain
    """
    namespace = "web.site"

    def __init__(self, domain: str):
        self.domain = domain
        self._reference = domain
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        return cls(reference)

    @property
    def reference(self) -> str:
        return self._reference


class DiscoursePost(ORN):
    """Discourse forum post resource identifier
    Format: orn:discourse.post:domain/topic_id/post_id
    """
    namespace = "discourse.post"

    def __init__(self, domain: str, topic_id: str, post_id: str):
        self.domain = domain
        self.topic_id = topic_id
        self.post_id = post_id
        self._reference = f"{domain}/{topic_id}/{post_id}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 3:
            raise ValueError(f"Invalid DiscoursePost reference: {reference}")
        return cls(parts[0], parts[1], parts[2])

    @property
    def reference(self) -> str:
        return self._reference


class DiscourseThread(ORN):
    """Discourse forum thread/topic resource identifier
    Format: orn:discourse.thread:domain/topic_id
    """
    namespace = "discourse.thread"

    def __init__(self, domain: str, topic_id: str):
        self.domain = domain
        self.topic_id = topic_id
        self._reference = f"{domain}/{topic_id}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid DiscourseThread reference: {reference}")
        return cls(parts[0], parts[1])

    @property
    def reference(self) -> str:
        return self._reference


class RSSFeed(ORN):
    """RSS feed resource identifier
    Format: orn:rss.feed:domain/feed_hash
    """
    namespace = "rss.feed"

    def __init__(self, domain: str, feed_url: str):
        self.domain = domain
        self.feed_url = feed_url
        # Create hash of feed URL for uniqueness
        self.feed_hash = hashlib.sha256(feed_url.encode('utf-8')).hexdigest()[:16]
        self._reference = f"{domain}/{self.feed_hash}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid RSSFeed reference: {reference}")
        # We can't recover the feed URL from the hash, so we'll use a placeholder
        return cls(parts[0], f"https://{parts[0]}/feed")

    @property
    def reference(self) -> str:
        return self._reference


class RSSItem(ORN):
    """RSS feed item resource identifier
    Format: orn:rss.item:domain/item_guid_hash
    """
    namespace = "rss.item"

    def __init__(self, domain: str, item_guid: str):
        self.domain = domain
        self.item_guid = item_guid
        # Hash the GUID to ensure consistent length
        self.guid_hash = hashlib.sha256(item_guid.encode('utf-8')).hexdigest()[:16]
        self._reference = f"{domain}/{self.guid_hash}"
        super().__init__()

    @classmethod
    def from_reference(cls, reference: str):
        """Create instance from reference string"""
        parts = reference.split('/')
        if len(parts) != 2:
            raise ValueError(f"Invalid RSSItem reference: {reference}")
        # We can't recover the GUID from the hash, so we'll use a placeholder
        return cls(parts[0], f"guid-{parts[1]}")

    @property
    def reference(self) -> str:
        return self._reference