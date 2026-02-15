"""
KOI Protocol - Knowledge Object

Phase 3: Knowledge representation for the handler chain pipeline.
String-based RIDs for backward compatibility with Regen's coordinator,
with rid_namespace auto-parsed for BlockScience-style handler filtering.

Reference: koi-research/sources/blockscience/koi-net/src/koi_net/processor/knowledge_object.py
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from pydantic import BaseModel, Field, model_validator


def _parse_rid_namespace(rid: str) -> Optional[str]:
    """Parse RID namespace from a RID string.

    Examples:
        "orn:twitter.tweet:user/tweet" → "twitter.tweet"
        "orn:web.page:domain/hash" → "web.page"
        "https://example.com" → None  (URI, no namespace)
        "regen.unknown:id" → "regen.unknown"
    """
    if not rid:
        return None

    # ORN format: "orn:<namespace>:<path>"
    orn_match = re.match(r'^orn:([^:]+):', rid)
    if orn_match:
        return orn_match.group(1)

    # URI format — no namespace
    if rid.startswith(("http://", "https://", "ftp://")):
        return None

    # Generic "namespace:path" format
    colon_match = re.match(r'^([^/:]+):', rid)
    if colon_match:
        return colon_match.group(1)

    return None


class KnowledgeObject(BaseModel):
    """Knowledge representation flowing through the pipeline.

    Uses string RIDs for backward compat with Regen's coordinator.
    rid_namespace is auto-parsed for handler filtering.
    raw_event_data preserves original event dict (READ-ONLY after construction).
    """

    rid: str
    rid_namespace: Optional[str] = None
    manifest: Optional[Any] = None  # Manifest from bundle_system
    contents: Optional[Dict[str, Any]] = None
    event_type: Optional[str] = None
    normalized_event_type: Optional[str] = None
    source: Optional[str] = None
    network_targets: Set[str] = Field(default_factory=set)
    raw_event_data: Optional[Dict[str, Any]] = None
    result_status: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def _auto_parse_namespace(self) -> "KnowledgeObject":
        """Auto-parse rid_namespace from rid string if not set."""
        if self.rid_namespace is None:
            self.rid_namespace = _parse_rid_namespace(self.rid)
        return self

    @classmethod
    def from_rid(
        cls,
        rid_str: str,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> "KnowledgeObject":
        """Create from a bare RID string."""
        return cls(rid=rid_str, event_type=event_type, source=source)

    @classmethod
    def from_bundle(
        cls,
        bundle,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> "KnowledgeObject":
        """Create from a Bundle object."""
        return cls(
            rid=bundle.rid,
            manifest=bundle.manifest,
            contents=bundle.contents,
            event_type=event_type,
            source=source,
        )

    @classmethod
    def from_event_data(cls, event_data: Dict[str, Any]) -> "KnowledgeObject":
        """Create from a raw event data dict (as received by broadcast endpoints).

        Parses RID, extracts bundle if present, stores raw_event_data.
        """
        rid = event_data.get("rid", "")
        event_type = event_data.get("event_type")
        source = event_data.get("source_node")

        manifest = None
        contents = None
        bundle_data = event_data.get("bundle")
        if isinstance(bundle_data, dict):
            manifest_data = bundle_data.get("manifest")
            contents = bundle_data.get("contents")
            if isinstance(manifest_data, dict):
                from ..core.bundle_system import Manifest
                manifest = Manifest.from_dict(manifest_data)

        return cls(
            rid=rid,
            manifest=manifest,
            contents=contents,
            event_type=event_type,
            source=source,
            raw_event_data=event_data,
        )
