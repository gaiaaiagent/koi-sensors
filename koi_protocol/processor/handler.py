"""
KOI Protocol - Handler Types and Registration

Phase 3: Handler chain architecture aligned with BlockScience's koi-net processor.

Reference: koi-research/sources/blockscience/koi-net/src/koi_net/processor/handler.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Optional, Sequence


class StopChain:
    """Sentinel indicating a handler wants to stop the pipeline chain.

    Matches BlockScience's StopChain exactly. Handlers return STOP_CHAIN
    to halt all further processing in the current phase and pipeline.
    """
    pass


STOP_CHAIN = StopChain()
"""Singleton sentinel — return this from a handler to stop the chain."""


class HandlerType(StrEnum):
    """Five-phase handler types matching BlockScience's pipeline.

    Pipeline executes in order: RID → Manifest → Bundle → Network → Final
    """
    RID = "rid"
    Manifest = "manifest"
    Bundle = "bundle"
    Network = "network"
    Final = "final"


@dataclass
class PipelineStop:
    """Typed result when a pipeline is halted by a handler.

    Replaces fragile tuple returns. Contains the mutated kobj at stop time
    so callers can inspect result_status and other fields.
    """
    kobj: Any  # KnowledgeObject — Any to avoid circular import


@dataclass
class KnowledgeHandler:
    """A registered handler in the pipeline.

    Handlers can be sync or async — the pipeline detects and handles both.
    Filtering is by handler_type (required), rid_types (optional namespace strings),
    and event_types (optional event type strings).
    """
    func: Callable
    handler_type: HandlerType
    rid_types: Sequence[str] = field(default_factory=list)
    event_types: Sequence[str] = field(default_factory=list)

    @staticmethod
    def create(
        handler_type: HandlerType,
        rid_types: Sequence[str] | None = None,
        event_types: Sequence[str] | None = None,
    ):
        """Decorator to create a KnowledgeHandler from a function.

        Usage::

            @KnowledgeHandler.create(HandlerType.Bundle, rid_types=["twitter.tweet"])
            async def my_handler(coordinator, kobj):
                ...
        """
        def decorator(func: Callable) -> KnowledgeHandler:
            return KnowledgeHandler(
                func=func,
                handler_type=handler_type,
                rid_types=list(rid_types or []),
                event_types=list(event_types or []),
            )
        return decorator
