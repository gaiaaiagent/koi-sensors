"""
KOI Protocol - Knowledge Pipeline

Phase 3: Async 5-phase pipeline matching BlockScience's handler chain architecture.
Executes handler chains in order: RID → Manifest → Bundle → Network → Final.

Reference: koi-research/sources/blockscience/koi-net/src/koi_net/processor/knowledge_pipeline.py
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional, Sequence

from .handler import (
    HandlerType,
    KnowledgeHandler,
    PipelineStop,
    StopChain,
    STOP_CHAIN,
)
from .knowledge_object import KnowledgeObject


class KnowledgePipeline:
    """Async 5-phase pipeline for event processing.

    Replaces monolithic inline broadcast logic with composable handlers.
    Each handler chain filters by handler_type, rid_namespace, and event_type.

    Usage::

        pipeline = KnowledgePipeline(coordinator=coord)
        pipeline.add_handler(my_handler)

        result = await pipeline.process(kobj)
        if isinstance(result, PipelineStop):
            # Pipeline was halted
            stopped_kobj = result.kobj
        else:
            # Normal completion
            final_kobj = result
    """

    # Pipeline phase execution order
    PHASE_ORDER = [
        HandlerType.RID,
        HandlerType.Manifest,
        HandlerType.Bundle,
        HandlerType.Network,
        HandlerType.Final,
    ]

    def __init__(
        self,
        coordinator: Any = None,
        default_handlers: Sequence[KnowledgeHandler] | None = None,
    ):
        self.coordinator = coordinator
        self.handlers: list[KnowledgeHandler] = []
        if default_handlers:
            for h in default_handlers:
                self.handlers.append(h)

    def add_handler(self, handler: KnowledgeHandler) -> None:
        """Register a handler explicitly."""
        self.handlers.append(handler)

    def register_handler(
        self,
        handler_type: HandlerType,
        rid_types: Sequence[str] | None = None,
        event_types: Sequence[str] | None = None,
    ) -> Callable:
        """Decorator to register a handler function.

        Usage::

            @pipeline.register_handler(HandlerType.Bundle)
            async def my_handler(coordinator, kobj):
                ...
        """
        def decorator(func: Callable) -> KnowledgeHandler:
            handler = KnowledgeHandler(
                func=func,
                handler_type=handler_type,
                rid_types=list(rid_types or []),
                event_types=list(event_types or []),
            )
            self.handlers.append(handler)
            return handler
        return decorator

    async def call_handler_chain(
        self,
        handler_type: HandlerType,
        kobj: KnowledgeObject,
    ) -> KnowledgeObject | PipelineStop:
        """Execute all handlers of a given type, filtering by rid_namespace and event_type.

        Each handler receives a deep copy of kobj. If a handler returns a modified
        KnowledgeObject, it becomes the kobj for subsequent handlers. If a handler
        returns STOP_CHAIN, processing halts and returns PipelineStop with the
        mutated kobj copy.

        Returns the final kobj or PipelineStop.
        """
        for handler in self.handlers:
            if handler.handler_type != handler_type:
                continue

            # Filter by rid_types (namespace strings)
            if handler.rid_types and kobj.rid_namespace not in handler.rid_types:
                continue

            # Filter by event_types
            if handler.event_types and kobj.event_type not in handler.event_types:
                continue

            # Deep copy to isolate handler mutations
            kobj_copy = kobj.model_copy(deep=True)

            # Call handler — supports both sync and async
            result = handler.func(coordinator=self.coordinator, kobj=kobj_copy)
            if inspect.isawaitable(result):
                result = await result

            if isinstance(result, StopChain):
                return PipelineStop(kobj=kobj_copy)

            if isinstance(result, KnowledgeObject):
                kobj = result
            # If result is None, kobj stays unchanged

        return kobj

    async def process(self, kobj: KnowledgeObject) -> KnowledgeObject | PipelineStop:
        """Run the full 5-phase pipeline.

        Phases execute in order: RID → Manifest → Bundle → Network → Final.
        If any handler returns STOP_CHAIN, the pipeline halts and returns PipelineStop.

        No cache writes — cache writing is done exclusively by koi_node.handle_event().
        """
        for phase in self.PHASE_ORDER:
            result = await self.call_handler_chain(phase, kobj)
            if isinstance(result, PipelineStop):
                return result
            kobj = result

        return kobj
