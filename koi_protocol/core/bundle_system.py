"""
KOI Protocol - Bundle and Manifest System
Implementation of Bundles and Manifests compliant with KOI-net specification
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass, asdict
from .rid_system import RID


@dataclass
class Manifest:
    """KOI Bundle Manifest containing metadata and hash"""
    
    rid: str  # RID as string
    timestamp: str  # ISO format timestamp
    content_hash: str  # SHA-256 hash of content
    size_bytes: int  # Content size in bytes
    content_type: str  # MIME type or content type
    version: str = "1.0"  # Manifest version
    metadata: Optional[Dict[str, Any]] = None
    
    @classmethod
    def generate(cls, rid: RID, content: Any, content_type: str = "application/json", 
                metadata: Optional[Dict[str, Any]] = None) -> 'Manifest':
        """Generate manifest from content"""
        
        # Serialize content for hashing
        if isinstance(content, (dict, list)):
            content_bytes = json.dumps(content, sort_keys=True).encode('utf-8')
        elif isinstance(content, str):
            content_bytes = content.encode('utf-8')
        else:
            content_bytes = str(content).encode('utf-8')
        
        # Generate hash
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        
        return cls(
            rid=rid.to_string(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            content_hash=content_hash,
            size_bytes=len(content_bytes),
            content_type=content_type,
            metadata=metadata or {}
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to dictionary"""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert manifest to JSON string"""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Manifest':
        """Create manifest from dictionary"""
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Manifest':
        """Create manifest from JSON string"""
        return cls.from_dict(json.loads(json_str))
    
    def verify_content(self, content: Any) -> bool:
        """Verify content matches manifest hash"""
        if isinstance(content, (dict, list)):
            content_bytes = json.dumps(content, sort_keys=True).encode('utf-8')
        elif isinstance(content, str):
            content_bytes = content.encode('utf-8')
        else:
            content_bytes = str(content).encode('utf-8')
        
        actual_hash = hashlib.sha256(content_bytes).hexdigest()
        return actual_hash == self.content_hash


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
        """Verify bundle integrity"""
        return self.manifest.verify_content(self.contents)
    
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
    
    # Bundle metadata
    bundle_metadata = {
        "source": document.get("source"),
        "source_type": document.get("source_type"),
        "collection_method": document.get("metadata", {}).get("collection_method"),
        "original_id": document.get("id")
    }
    
    return Bundle.generate(
        rid=rid,
        contents=bundle_contents,
        content_type="application/json",
        metadata=bundle_metadata
    )