"""
KOI Sensor Network - Web Content RID Types
Resource Identifiers for websites, discourse forums, and web pages
"""

import hashlib
from typing import Optional
from rid_lib import ORN


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
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.domain}/{self.path_hash}"


class WebSite(ORN):
    """Website resource identifier
    Format: orn:web.site:domain
    """
    namespace = "web.site"
    
    def __init__(self, domain: str):
        self.domain = domain
        super().__init__()
    
    @property
    def reference(self) -> str:
        return self.domain


class DiscoursePost(ORN):
    """Discourse forum post resource identifier
    Format: orn:discourse.post:domain/topic_id/post_id
    """
    namespace = "discourse.post"
    
    def __init__(self, domain: str, topic_id: str, post_id: str):
        self.domain = domain
        self.topic_id = topic_id
        self.post_id = post_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.domain}/{self.topic_id}/{self.post_id}"


class DiscourseThread(ORN):
    """Discourse forum thread/topic resource identifier
    Format: orn:discourse.thread:domain/topic_id
    """
    namespace = "discourse.thread"
    
    def __init__(self, domain: str, topic_id: str):
        self.domain = domain
        self.topic_id = topic_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.domain}/{self.topic_id}"


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
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.domain}/{self.feed_hash}"


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
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.domain}/{self.guid_hash}"