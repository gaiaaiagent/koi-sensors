"""
KOI Protocol - Bundle and Manifest System
Implementation of Bundles and Manifests compliant with KOI-net specification

Phase 0 (P0) Alignment: Dual-hash support for rid-lib compatibility.
- sha256_hash: JCS-canonicalized hash (rid-lib compatible)
- legacy_content_hash: json.dumps(sort_keys=True) hash (backward compatibility)
- content_hash: Alias for sha256_hash (new code paths should use sha256_hash)

Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass, asdict, field
from .rid_system import RID

# Import rid-lib for JCS canonicalization (P0 alignment)
try:
    from rid_lib.ext.utils import sha256_hash_json as ridlib_sha256_hash_json
    RID_LIB_AVAILABLE = True
except ImportError:
    RID_LIB_AVAILABLE = False
    ridlib_sha256_hash_json = None


def _legacy_hash_content(content: Any) -> tuple[str, bytes]:
    """
    Compute legacy hash using json.dumps(sort_keys=True).
    Returns (hash_hex, content_bytes).
    """
    if isinstance(content, (dict, list)):
        content_bytes = json.dumps(content, sort_keys=True).encode('utf-8')
    elif isinstance(content, str):
        content_bytes = content.encode('utf-8')
    else:
        content_bytes = str(content).encode('utf-8')

    content_hash = hashlib.sha256(content_bytes).hexdigest()
    return content_hash, content_bytes


def _ridlib_hash_content(content: Any) -> str:
    """
    Compute hash using rid-lib JCS canonicalization.
    Falls back to legacy hash if rid-lib is not available.
    """
    if RID_LIB_AVAILABLE and isinstance(content, (dict, list)):
        return ridlib_sha256_hash_json(content)
    else:
        # Fallback to legacy hash for non-dict/list or if rid-lib not available
        hash_hex, _ = _legacy_hash_content(content)
        return hash_hex


# Content type registry for different bundle types
CONTENT_TYPES = {
    "application/json": {
        "extensions": [".json"],
        "description": "Generic JSON content"
    },
    "application/kg+json": {
        "extensions": [".kg.json"],
        "description": "Knowledge Graph extraction results"
    }
}


@dataclass
class Manifest:
    """
    KOI Bundle Manifest containing metadata and hash.

    P0 Alignment: Now includes dual-hash support:
    - sha256_hash: rid-lib JCS hash (for KOI-net interoperability)
    - legacy_content_hash: json.dumps(sort_keys=True) hash (backward compatibility)
    - content_hash: Property that returns sha256_hash (for new code paths)
    """

    rid: str  # RID as string
    timestamp: str  # ISO format timestamp
    sha256_hash: str  # SHA-256 hash using rid-lib JCS canonicalization
    size_bytes: int  # Content size in bytes
    content_type: str  # MIME type or content type
    version: str = "1.0"  # Manifest version
    metadata: Optional[Dict[str, Any]] = None
    legacy_content_hash: Optional[str] = None  # Legacy hash for backward compatibility

    @property
    def content_hash(self) -> str:
        """
        Alias for sha256_hash for backward compatibility.
        New code paths should use sha256_hash directly.
        """
        return self.sha256_hash

    @classmethod
    def generate(cls, rid: RID, content: Any, content_type: str = "application/json",
                metadata: Optional[Dict[str, Any]] = None) -> 'Manifest':
        """Generate manifest from content with dual-hash support."""

        # Compute legacy hash (json.dumps sort_keys=True) for backward compatibility
        legacy_hash, content_bytes = _legacy_hash_content(content)

        # Compute rid-lib JCS hash for KOI-net interoperability
        ridlib_hash = _ridlib_hash_content(content)

        return cls(
            rid=rid.to_string(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            sha256_hash=ridlib_hash,
            size_bytes=len(content_bytes),
            content_type=content_type,
            metadata=metadata or {},
            legacy_content_hash=legacy_hash
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to dictionary with both hash fields."""
        result = {
            "rid": self.rid,
            "timestamp": self.timestamp,
            "sha256_hash": self.sha256_hash,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "version": self.version,
            "metadata": self.metadata,
            "legacy_content_hash": self.legacy_content_hash,
            # Also include content_hash for backward compatibility with consumers
            "content_hash": self.content_hash,
        }
        return result

    def to_json(self) -> str:
        """Convert manifest to JSON string"""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Manifest':
        """
        Create manifest from dictionary.
        Handles legacy manifests that only have content_hash.
        """
        # Handle legacy manifests with only content_hash
        sha256_hash = data.get('sha256_hash')
        legacy_content_hash = data.get('legacy_content_hash')
        content_hash = data.get('content_hash')

        # If sha256_hash is missing, fall back to content_hash
        if sha256_hash is None and content_hash is not None:
            sha256_hash = content_hash

        # If legacy_content_hash is missing but content_hash exists, use it
        if legacy_content_hash is None and content_hash is not None:
            legacy_content_hash = content_hash

        return cls(
            rid=data['rid'],
            timestamp=data['timestamp'],
            sha256_hash=sha256_hash,
            size_bytes=data['size_bytes'],
            content_type=data['content_type'],
            version=data.get('version', '1.0'),
            metadata=data.get('metadata'),
            legacy_content_hash=legacy_content_hash
        )

    @classmethod
    def from_json(cls, json_str: str) -> 'Manifest':
        """Create manifest from JSON string"""
        return cls.from_dict(json.loads(json_str))

    def verify_content(self, content: Any) -> bool:
        """
        Verify content matches manifest sha256_hash (rid-lib JCS).
        This is the primary verification method for KOI-net interoperability.
        """
        actual_hash = _ridlib_hash_content(content)
        return actual_hash == self.sha256_hash

    def verify_legacy_content(self, content: Any) -> bool:
        """
        Verify content matches legacy_content_hash (json.dumps sort_keys=True).
        Use this for backward compatibility with pre-P0 data.
        """
        if self.legacy_content_hash is None:
            return False
        actual_hash, _ = _legacy_hash_content(content)
        return actual_hash == self.legacy_content_hash


@dataclass
class Bundle:
    """KOI Bundle containing content and manifest"""
    
    rid: str  # RID as string
    manifest: Manifest
    contents: Any  # Bundle contents
    
    @classmethod
    def generate(cls, rid: RID, contents: Any, content_type: str = "application/json",
                metadata: Optional[Dict[str, Any]] = None) -> 'Bundle':
        """Generate bundle with manifest"""
        
        manifest = Manifest.generate(
            rid=rid,
            content=contents,
            content_type=content_type,
            metadata=metadata
        )
        
        return cls(
            rid=rid.to_string(),
            manifest=manifest,
            contents=contents
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert bundle to dictionary"""
        return {
            "rid": self.rid,
            "manifest": self.manifest.to_dict(),
            "contents": self.contents
        }
    
    def to_json(self) -> str:
        """Convert bundle to JSON string"""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Bundle':
        """Create bundle from dictionary"""
        return cls(
            rid=data["rid"],
            manifest=Manifest.from_dict(data["manifest"]),
            contents=data["contents"]
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Bundle':
        """Create bundle from JSON string"""
        return cls.from_dict(json.loads(json_str))
    
    def verify_integrity(self) -> bool:
        """
        Verify bundle integrity using sha256_hash (rid-lib JCS).
        This is the primary verification method for KOI-net interoperability.
        """
        return self.manifest.verify_content(self.contents)

    def verify_legacy_integrity(self) -> bool:
        """
        Verify bundle integrity using legacy_content_hash (json.dumps sort_keys=True).
        Use this for backward compatibility with pre-P0 data.
        """
        return self.manifest.verify_legacy_content(self.contents)

    def get_rid(self) -> RID:
        """Get RID object from string"""
        return RID.parse(self.rid)


@dataclass
class KOIEvent:
    """KOI FUN Event (Forget, Update, New)"""
    
    event_type: str  # "NEW", "UPDATE", "FORGET"
    rid: str  # RID as string
    timestamp: str  # ISO format timestamp
    source_node: str  # Node that generated the event
    bundle: Optional[Bundle] = None  # Bundle for NEW/UPDATE events
    reason: Optional[str] = None  # Reason for FORGET events
    
    @classmethod
    def new_event(cls, bundle: Bundle, source_node: str) -> 'KOIEvent':
        """Create NEW event"""
        return cls(
            event_type="NEW",
            rid=bundle.rid,
            timestamp=datetime.now(timezone.utc).isoformat(),
            source_node=source_node,
            bundle=bundle
        )
    
    @classmethod
    def update_event(cls, bundle: Bundle, source_node: str) -> 'KOIEvent':
        """Create UPDATE event"""
        return cls(
            event_type="UPDATE",
            rid=bundle.rid,
            timestamp=datetime.now(timezone.utc).isoformat(),
            source_node=source_node,
            bundle=bundle
        )
    
    @classmethod
    def forget_event(cls, rid: RID, source_node: str, reason: str = None) -> 'KOIEvent':
        """Create FORGET event"""
        return cls(
            event_type="FORGET",
            rid=rid.to_string(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            source_node=source_node,
            reason=reason
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary"""
        result = {
            "event_type": self.event_type,
            "rid": self.rid,
            "timestamp": self.timestamp,
            "source_node": self.source_node
        }
        
        if self.bundle:
            result["bundle"] = self.bundle.to_dict()
        
        if self.reason:
            result["reason"] = self.reason
        
        return result
    
    def to_json(self) -> str:
        """Convert event to JSON string"""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KOIEvent':
        """Create event from dictionary"""
        bundle = None
        if "bundle" in data:
            bundle = Bundle.from_dict(data["bundle"])
        
        return cls(
            event_type=data["event_type"],
            rid=data["rid"],
            timestamp=data["timestamp"],
            source_node=data["source_node"],
            bundle=bundle,
            reason=data.get("reason")
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> 'KOIEvent':
        """Create event from JSON string"""
        return cls.from_dict(json.loads(json_str))


def document_to_bundle(document: Dict[str, Any], source_node: str = "regen-collector") -> Bundle:
    """Convert existing Document format to KOI Bundle"""
    from .rid_system import document_to_rid
    
    # Generate RID from document
    rid = document_to_rid(document)
    if not rid:
        raise ValueError(f"Could not generate RID for document: {document.get('id', 'unknown')}")
    
    # Prepare bundle contents
    bundle_contents = {
        "document": {
            "id": document.get("id"),
            "source": document.get("source"),
            "source_type": document.get("source_type"),
            "url": document.get("url"),
            "title": document.get("title"),
            "content": document.get("content"),
            "author": document.get("author"),
            "tags": document.get("tags", []),
            "collected_at": document.get("collected_at"),
            "last_modified": document.get("last_modified")
        },
        "metadata": document.get("metadata", {}),
        "processing": {
            "koi_rid": rid.to_string(),
            "converted_at": datetime.now(timezone.utc).isoformat(),
            "source_node": source_node
        }
    }
    
    # Bundle metadata - include publication date info
    bundle_metadata = {
        "source": document.get("source"),
        "source_type": document.get("source_type"),
        "collection_method": document.get("metadata", {}).get("collection_method"),
        "original_id": document.get("id")
    }

    # CRITICAL: Include URL fields for event bridge URL extraction
    # Event bridge checks bundle.manifest.metadata for 'url' and 'source_url'
    if document.get("url"):
        bundle_metadata["url"] = document.get("url")
    if document.get("source_url"):
        bundle_metadata["source_url"] = document.get("source_url")

    # Also check metadata for URL fields as fallback
    doc_metadata = document.get("metadata", {})
    if not bundle_metadata.get("url") and doc_metadata.get("url"):
        bundle_metadata["url"] = doc_metadata.get("url")
    if not bundle_metadata.get("source_url") and doc_metadata.get("source_url"):
        bundle_metadata["source_url"] = doc_metadata.get("source_url")

    # CRITICAL: Pass through publication date metadata for digest generation
    if "published_at" in doc_metadata:
        bundle_metadata["published_at"] = doc_metadata["published_at"]
        bundle_metadata["published_confidence"] = doc_metadata.get("published_confidence", 0.5)
    if "last_modified" in doc_metadata:
        bundle_metadata["last_modified"] = doc_metadata["last_modified"]

    # CRITICAL: Pass through Code Graph metadata for provenance tracking
    if "file_path" in doc_metadata:
        bundle_metadata["file_path"] = doc_metadata["file_path"]
    if "repo" in doc_metadata:
        bundle_metadata["repo"] = doc_metadata["repo"]
    if "branch" in doc_metadata:
        bundle_metadata["branch"] = doc_metadata["branch"]
    if "commit_sha" in doc_metadata:
        bundle_metadata["commit_sha"] = doc_metadata["commit_sha"]
    if "commit_date" in doc_metadata:
        bundle_metadata["commit_date"] = doc_metadata["commit_date"]

    return Bundle.generate(
        rid=rid,
        contents=bundle_contents,
        content_type="application/json",
        metadata=bundle_metadata
    )