"""
KOI Protocol - Resource Identifier (RID) System
Implementation of RIDs compliant with KOI-net specification
"""

import hashlib
import re
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
from abc import ABC, abstractmethod


class RID(ABC):
    """Base Resource Identifier class following KOI-net specification"""
    
    def __init__(self, context: str, reference: str):
        self.context = context
        self.reference = reference
        self._validate()
    
    def _validate(self):
        """Validate RID format compliance"""
        if not self.context or not self.reference:
            raise ValueError("Context and reference cannot be empty")
        
        if ':' in self.reference:
            raise ValueError("Reference cannot contain ':' character")
        
        # Validate context format (letters, numbers, hyphens, dots)
        if not re.match(r'^[a-zA-Z0-9\-\.]+$', self.context):
            raise ValueError("Invalid context format")
    
    def to_string(self) -> str:
        """Convert RID to string representation"""
        return f"{self.context}:{self.reference}"
    
    def __str__(self) -> str:
        return self.to_string()
    
    def __repr__(self) -> str:
        return f"RID('{self.to_string()}')"
    
    def __hash__(self) -> int:
        return hash(self.to_string())
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, RID):
            return False
        return self.to_string() == other.to_string()
    
    @classmethod
    def parse(cls, rid_string: str) -> 'RID':
        """Parse RID from string format"""
        if ':' not in rid_string:
            raise ValueError("Invalid RID format: missing ':' separator")
        
        context, reference = rid_string.split(':', 1)
        return GenericRID(context, reference)


class GenericRID(RID):
    """Generic RID implementation for any context:reference pair"""
    
    def __init__(self, context: str, reference: str):
        super().__init__(context, reference)


class ORN(RID):
    """Object Reference Name - specific RID format for platform content"""
    
    namespace: str = None  # Override in subclasses
    
    def __init__(self):
        if self.namespace is None:
            raise ValueError("Namespace must be defined in ORN subclasses")
        super().__init__("orn", f"{self.namespace}:{self.reference}")
    
    @property
    @abstractmethod
    def reference(self) -> str:
        """Generate reference string for this ORN"""
        pass


# Platform-specific ORN implementations
class TwitterTweetRID(ORN):
    """Twitter tweet RID: orn:twitter.tweet:user_id/tweet_id"""
    namespace = "twitter.tweet"
    
    def __init__(self, user_id: str, tweet_id: str):
        self.user_id = user_id
        self.tweet_id = tweet_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.user_id}/{self.tweet_id}"


class DiscoursePostRID(ORN):
    """Discourse post RID: orn:discourse.post:domain/topic_id/post_id"""
    namespace = "discourse.post"
    
    def __init__(self, domain: str, topic_id: str, post_id: str):
        self.domain = domain
        self.topic_id = topic_id
        self.post_id = post_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.domain}/{self.topic_id}/{self.post_id}"


class NotionPageRID(ORN):
    """Notion page RID: orn:notion.page:workspace_id/page_id"""
    namespace = "notion.page"
    
    def __init__(self, workspace_id: str, page_id: str):
        self.workspace_id = workspace_id
        self.page_id = page_id
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.workspace_id}/{self.page_id}"


class WebPageRID(ORN):
    """Web page RID: orn:web.page:domain/path_hash"""
    namespace = "web.page"
    
    def __init__(self, domain: str, url: str):
        self.domain = domain
        self.url = url
        # Create hash of full URL for uniqueness
        self.path_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.domain}/{self.path_hash}"


class GitHubFileRID(ORN):
    """GitHub file RID: orn:github.file:owner/repo/branch/file_path_hash"""
    namespace = "github.file"
    
    def __init__(self, owner: str, repo: str, branch: str, file_path: str):
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.file_path = file_path
        self.path_hash = hashlib.sha256(file_path.encode('utf-8')).hexdigest()[:16]
        super().__init__()
    
    @property
    def reference(self) -> str:
        return f"{self.owner}/{self.repo}/{self.branch}/{self.path_hash}"


class RIDRegistry:
    """Registry for RID types and factory methods"""
    
    def __init__(self):
        self._rid_types: Dict[str, type] = {}
        self._register_builtin_types()
    
    def _register_builtin_types(self):
        """Register built-in RID types"""
        self.register("twitter.tweet", TwitterTweetRID)
        self.register("discourse.post", DiscoursePostRID)
        self.register("notion.page", NotionPageRID)
        self.register("web.page", WebPageRID)
        self.register("github.file", GitHubFileRID)
    
    def register(self, namespace: str, rid_class: type):
        """Register a RID type for a namespace"""
        self._rid_types[namespace] = rid_class
    
    def create_from_string(self, rid_string: str) -> RID:
        """Create RID instance from string"""
        return RID.parse(rid_string)
    
    def create_from_data(self, namespace: str, **kwargs) -> Optional[RID]:
        """Create RID instance from structured data"""
        rid_class = self._rid_types.get(namespace)
        if not rid_class:
            return None
        
        try:
            return rid_class(**kwargs)
        except Exception:
            return None


# Global RID registry instance
rid_registry = RIDRegistry()


# Utility functions for existing Document model integration
def document_to_rid(document: Dict[str, Any]) -> Optional[RID]:
    """Convert existing Document to KOI RID"""
    source_type = document.get('source_type', '')
    source = document.get('source', '')
    
    # Twitter documents
    if source_type == 'twitter':
        # Extract user_id and tweet_id from metadata or URL
        metadata = document.get('metadata', {})
        tweet_id = metadata.get('id') or metadata.get('tweet_id')
        author_id = metadata.get('author_id') or metadata.get('user_id')
        
        if tweet_id and author_id:
            return TwitterTweetRID(str(author_id), str(tweet_id))
    
    # Discourse documents
    elif source_type == 'discourse':
        url = document.get('url', '')
        # Parse forum.regen.network/t/topic-name/123/4 format
        if '/t/' in url:
            parts = url.split('/')
            if len(parts) >= 4:
                domain = parts[2]  # forum.regen.network
                topic_id = parts[-2] if parts[-1].isdigit() else parts[-1]
                post_id = parts[-1] if parts[-1].isdigit() else "1"
                return DiscoursePostRID(domain, topic_id, post_id)
    
    # Notion documents
    elif source_type == 'notion':
        metadata = document.get('metadata', {})
        page_id = metadata.get('id') or metadata.get('page_id')
        workspace_id = metadata.get('workspace_id', 'regen')  # Default workspace
        
        if page_id:
            return NotionPageRID(workspace_id, page_id)
    
    # Web documents
    elif source_type in ['web', 'website']:
        url = document.get('url', '')
        if url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc
                return WebPageRID(domain, url)
            except Exception:
                pass
    
    # GitHub documents
    elif source_type in ['github', 'git']:
        source = document.get('source', '')
        file_path = document.get('metadata', {}).get('file_path', '')
        
        # Parse github:owner/repo format
        if ':' in source:
            repo_part = source.split(':', 1)[1]
            if '/' in repo_part:
                owner, repo = repo_part.split('/', 1)
                branch = document.get('metadata', {}).get('branch', 'main')
                if file_path:
                    return GitHubFileRID(owner, repo, branch, file_path)
    
    # Fallback to generic RID
    document_id = document.get('id', '')
    if document_id:
        return GenericRID(f"regen.{source_type}", document_id)
    
    return None


def generate_rid_for_document(document: Dict[str, Any]) -> str:
    """Generate RID string for existing Document"""
    rid = document_to_rid(document)
    return rid.to_string() if rid else f"regen.unknown:{document.get('id', 'unknown')}"