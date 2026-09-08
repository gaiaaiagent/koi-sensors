"""
KOI Protocol - Resource Identifier (RID) System
Implementation of RIDs compliant with KOI-net specification

Phase 0 (P0) Alignment: Updated to support:
- ORNs with multiple colons (orn:namespace:reference)
- URIs with ports (https://example.com:8080/path)
- All valid URI schemes as RID contexts

Phase 2: rid-lib is now a first-class dependency.
Custom ORN subclasses replaced with re-exports from shared/rid_types/.

Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
"""

from typing import Optional, Dict, Any
from abc import ABC, abstractmethod

# rid-lib is a required dependency (Phase 2)
from rid_lib import RID as RidLibRID
from rid_lib.utils import parse_rid_string as ridlib_parse_rid_string
from rid_lib.consts import NAMESPACE_SCHEMES

# Re-export rid-lib ORN subclasses from shared/rid_types/ (Phase 2)
# These replace the custom classes that were previously defined here.
# Backward-compatible aliases (e.g. TwitterTweetRID) are provided below.
from shared.rid_types.social_media import TwitterTweet, YouTubeVideo
from shared.rid_types.web_content import WebPage, DiscoursePost
from shared.rid_types.productivity import NotionPage
from shared.rid_types.dev_tools import GitHubFile
from shared.rid_types.communication import GmailMessage, GmailAttachment

# Backward-compatible aliases for existing consumers
TwitterTweetRID = TwitterTweet
DiscoursePostRID = DiscoursePost
NotionPageRID = NotionPage
WebPageRID = WebPage
GitHubFileRID = GitHubFile
GmailMessageRID = GmailMessage
GmailAttachmentRID = GmailAttachment
YouTubeVideoRID = YouTubeVideo


def _parse_rid_components(rid_string: str) -> tuple[str, str]:
    """
    Parse RID string into context and reference components.

    Handles:
    - ORNs: orn:namespace:reference -> context="orn:namespace", reference="reference"
    - URNs: urn:namespace:reference -> context="urn:namespace", reference="reference"
    - URIs: https://example.com:8080/path -> context="https", reference="//example.com:8080/path"
    - Generic: context:reference -> context="context", reference="reference"
    """
    if not isinstance(rid_string, str) or ':' not in rid_string:
        raise ValueError(f"Invalid RID format: '{rid_string}' - missing ':' separator")

    # Find the scheme (first colon-delimited component)
    first_colon = rid_string.find(':')
    scheme = rid_string[:first_colon]

    # Check if this is a namespace scheme (orn, urn)
    if scheme.lower() in NAMESPACE_SCHEMES:
        # For ORN/URN, the format is scheme:namespace:reference
        # The context is scheme:namespace, and reference is everything after
        remaining = rid_string[first_colon + 1:]
        second_colon = remaining.find(':')

        if second_colon < 0:
            # Only scheme:namespace, no reference (e.g., orn:slack.message)
            # This is incomplete but we'll handle it gracefully
            context = rid_string
            reference = ""
        else:
            namespace = remaining[:second_colon]
            reference = remaining[second_colon + 1:]
            context = f"{scheme}:{namespace}"

        return context, reference
    else:
        # For URIs and generic RIDs, context is the scheme
        # and reference is everything after the first colon
        context = scheme
        reference = rid_string[first_colon + 1:]
        return context, reference


class RID(ABC):
    """
    Base Resource Identifier class following KOI-net specification.

    P0 Alignment: Updated to properly parse ORNs and URIs per rid-lib v3.
    All URIs can be valid RIDs (scheme:reference format).
    """

    def __init__(self, context: str, reference: str):
        self.context = context
        self.reference = reference
        self._validate()

    def _validate(self):
        """Validate RID format compliance"""
        if not self.context:
            raise ValueError("Context cannot be empty")

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
        """
        Parse RID from string format.

        P0 Alignment: Updated to handle:
        - ORNs: orn:namespace:reference (reference can contain ':')
        - URIs: https://example.com:8080/path (ports allowed)
        - Generic: context:reference
        """
        context, reference = _parse_rid_components(rid_string)
        return GenericRID(context, reference)


class GenericRID(RID):
    """Generic RID implementation for any context:reference pair"""

    def __init__(self, context: str, reference: str):
        super().__init__(context, reference)


# Re-export rid_lib.core.ORN for consumers that import it from here
from rid_lib.core import ORN


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
        self.register("gmail.message", GmailMessageRID)
        self.register("gmail.attachment", GmailAttachmentRID)

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

    # YouTube documents
    elif source_type == "youtube":
        metadata = document.get("metadata", {})
        video_id = metadata.get("video_id")
        channel_id = metadata.get("channel_id")

        if video_id and channel_id:
            return YouTubeVideoRID(channel_id, video_id)

    # Notion documents
    elif source_type == 'notion':
        metadata = document.get('metadata', {})
        page_id = metadata.get('id') or metadata.get('page_id')
        workspace_id = metadata.get('workspace_id', 'regen')  # Default workspace
        comment_id = metadata.get('comment_id')
        if comment_id:
            return GenericRID("orn:notion.comment", f"{workspace_id}/{comment_id}")

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
