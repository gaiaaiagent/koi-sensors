#!/usr/bin/env python3
"""
Phase 3 Session 3.1: Core Pipeline Infrastructure Tests

Tests for the processor/ package: KnowledgeObject, KnowledgePipeline,
HandlerType, handler registry, and chain execution.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from koi_protocol.processor import (
    HandlerType,
    KnowledgeHandler,
    KnowledgePipeline,
    KnowledgeObject,
    PipelineStop,
    StopChain,
    STOP_CHAIN,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


# ===========================================================================
# HandlerType enum
# ===========================================================================

class TestHandlerType:
    def test_enum_values_match_blockscience(self):
        """HandlerType values match BlockScience: RID, Manifest, Bundle, Network, Final."""
        assert HandlerType.RID == "rid"
        assert HandlerType.Manifest == "manifest"
        assert HandlerType.Bundle == "bundle"
        assert HandlerType.Network == "network"
        assert HandlerType.Final == "final"

    def test_all_five_types_exist(self):
        assert len(HandlerType) == 5


# ===========================================================================
# STOP_CHAIN sentinel
# ===========================================================================

class TestStopChain:
    def test_stop_chain_is_stopchain_instance(self):
        assert isinstance(STOP_CHAIN, StopChain)

    def test_stop_chain_singleton(self):
        """STOP_CHAIN is the module-level singleton."""
        from koi_protocol.processor.handler import STOP_CHAIN as imported
        assert imported is STOP_CHAIN


# ===========================================================================
# KnowledgeObject
# ===========================================================================

class TestKnowledgeObject:
    def test_from_rid_string(self):
        kobj = KnowledgeObject.from_rid("orn:twitter.tweet:user/tweet", event_type="NEW", source="sensor-1")
        assert kobj.rid == "orn:twitter.tweet:user/tweet"
        assert kobj.event_type == "NEW"
        assert kobj.source == "sensor-1"

    def test_rid_namespace_parsed_orn(self):
        """orn:twitter.tweet:user/tweet → 'twitter.tweet'"""
        kobj = KnowledgeObject(rid="orn:twitter.tweet:user/tweet")
        assert kobj.rid_namespace == "twitter.tweet"

    def test_rid_namespace_parsed_web_page(self):
        """orn:web.page:domain/hash → 'web.page'"""
        kobj = KnowledgeObject(rid="orn:web.page:domain/hash")
        assert kobj.rid_namespace == "web.page"

    def test_rid_namespace_none_for_uri(self):
        """https://example.com → None"""
        kobj = KnowledgeObject(rid="https://example.com")
        assert kobj.rid_namespace is None

    def test_rid_namespace_generic(self):
        """regen.unknown:id → 'regen.unknown'"""
        kobj = KnowledgeObject(rid="regen.unknown:id")
        assert kobj.rid_namespace == "regen.unknown"

    def test_from_event_data_with_bundle(self):
        event_data = {
            "event_type": "NEW",
            "rid": "orn:test.sensor:item/1",
            "timestamp": "2026-01-01T00:00:00Z",
            "source_node": "test-sensor-001",
            "bundle": {
                "rid": "orn:test.sensor:item/1",
                "manifest": {
                    "rid": "orn:test.sensor:item/1",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "sha256_hash": "abc123",
                    "content_hash": "abc123",
                },
                "contents": {"text": "hello"},
            },
        }
        kobj = KnowledgeObject.from_event_data(event_data)
        assert kobj.rid == "orn:test.sensor:item/1"
        assert kobj.event_type == "NEW"
        assert kobj.source == "test-sensor-001"
        assert kobj.manifest is not None
        assert kobj.contents == {"text": "hello"}
        assert kobj.raw_event_data == event_data

    def test_from_event_data_without_bundle(self):
        event_data = {
            "event_type": "NEW",
            "rid": "orn:test.sensor:item/2",
            "timestamp": "2026-01-01T00:00:00Z",
            "source_node": "test-sensor-001",
            "data": {"type": "sensor_heartbeat", "sensor_id": "s1"},
        }
        kobj = KnowledgeObject.from_event_data(event_data)
        assert kobj.manifest is None
        assert kobj.contents is None
        assert kobj.raw_event_data == event_data

    def test_raw_event_data_preserved(self):
        data = {"rid": "orn:test:x", "data": {"key": "val"}}
        kobj = KnowledgeObject.from_event_data(data)
        assert kobj.raw_event_data == data

    def test_from_bundle_object(self):
        from koi_protocol.core.bundle_system import Bundle, Manifest
        manifest = Manifest(
            rid="orn:test:b1", timestamp="2026-01-01T00:00:00Z",
            sha256_hash="abc", size_bytes=10, content_type="application/json",
        )
        bundle = Bundle(rid="orn:test:b1", manifest=manifest, contents={"x": 1})
        kobj = KnowledgeObject.from_bundle(bundle, event_type="UPDATE", source="s1")
        assert kobj.rid == "orn:test:b1"
        assert kobj.manifest is manifest
        assert kobj.contents == {"x": 1}
        assert kobj.event_type == "UPDATE"


# ===========================================================================
# Handler registration
# ===========================================================================

class TestHandlerRegistration:
    def test_decorator_creates_handler(self):
        @KnowledgeHandler.create(HandlerType.Bundle)
        def my_handler(coordinator, kobj):
            return None

        assert isinstance(my_handler, KnowledgeHandler)
        assert my_handler.handler_type == HandlerType.Bundle
        assert my_handler.rid_types == []
        assert my_handler.event_types == []

    def test_decorator_with_filters(self):
        @KnowledgeHandler.create(
            HandlerType.RID,
            rid_types=["twitter.tweet"],
            event_types=["NEW"],
        )
        def filtered_handler(coordinator, kobj):
            return None

        assert filtered_handler.rid_types == ["twitter.tweet"]
        assert filtered_handler.event_types == ["NEW"]

    def test_add_handler_explicit(self):
        pipeline = KnowledgePipeline()
        handler = KnowledgeHandler(func=lambda **kw: None, handler_type=HandlerType.Final)
        pipeline.add_handler(handler)
        assert len(pipeline.handlers) == 1

    def test_register_handler_decorator(self):
        pipeline = KnowledgePipeline()

        @pipeline.register_handler(HandlerType.Network)
        def net_handler(coordinator, kobj):
            return None

        assert len(pipeline.handlers) == 1
        assert pipeline.handlers[0].handler_type == HandlerType.Network


# ===========================================================================
# Handler chain filtering
# ===========================================================================

class TestHandlerChainFiltering:
    async def test_filter_by_handler_type(self):
        calls = []

        @KnowledgeHandler.create(HandlerType.Bundle)
        def bundle_h(coordinator, kobj):
            calls.append("bundle")
            return None

        @KnowledgeHandler.create(HandlerType.Network)
        def network_h(coordinator, kobj):
            calls.append("network")
            return None

        pipeline = KnowledgePipeline(default_handlers=[bundle_h, network_h])
        kobj = KnowledgeObject(rid="orn:test:x")
        await pipeline.call_handler_chain(HandlerType.Bundle, kobj)
        assert calls == ["bundle"]

    async def test_filter_by_rid_types(self):
        calls = []

        @KnowledgeHandler.create(HandlerType.Bundle, rid_types=["twitter.tweet"])
        def twitter_only(coordinator, kobj):
            calls.append("twitter")
            return None

        pipeline = KnowledgePipeline(default_handlers=[twitter_only])

        # Non-matching namespace
        kobj_web = KnowledgeObject(rid="orn:web.page:x")
        await pipeline.call_handler_chain(HandlerType.Bundle, kobj_web)
        assert calls == []

        # Matching namespace
        kobj_tw = KnowledgeObject(rid="orn:twitter.tweet:user/t1")
        await pipeline.call_handler_chain(HandlerType.Bundle, kobj_tw)
        assert calls == ["twitter"]

    async def test_filter_by_event_types(self):
        calls = []

        @KnowledgeHandler.create(HandlerType.RID, event_types=["NEW"])
        def new_only(coordinator, kobj):
            calls.append("new")
            return None

        pipeline = KnowledgePipeline(default_handlers=[new_only])

        kobj_update = KnowledgeObject(rid="orn:test:x", event_type="UPDATE")
        await pipeline.call_handler_chain(HandlerType.RID, kobj_update)
        assert calls == []

        kobj_new = KnowledgeObject(rid="orn:test:x", event_type="NEW")
        await pipeline.call_handler_chain(HandlerType.RID, kobj_new)
        assert calls == ["new"]


# ===========================================================================
# Sync and async handler support
# ===========================================================================

class TestHandlerAsyncSupport:
    async def test_async_handler_awaited(self):
        @KnowledgeHandler.create(HandlerType.Bundle)
        async def async_h(coordinator, kobj):
            kobj.result_status = "async_done"
            return kobj

        pipeline = KnowledgePipeline(default_handlers=[async_h])
        kobj = KnowledgeObject(rid="orn:test:x")
        result = await pipeline.call_handler_chain(HandlerType.Bundle, kobj)
        assert result.result_status == "async_done"

    async def test_sync_handler_works(self):
        @KnowledgeHandler.create(HandlerType.Bundle)
        def sync_h(coordinator, kobj):
            kobj.result_status = "sync_done"
            return kobj

        pipeline = KnowledgePipeline(default_handlers=[sync_h])
        kobj = KnowledgeObject(rid="orn:test:x")
        result = await pipeline.call_handler_chain(HandlerType.Bundle, kobj)
        assert result.result_status == "sync_done"

    async def test_mixed_sync_async_chain(self):
        order = []

        @KnowledgeHandler.create(HandlerType.Bundle)
        def sync_first(coordinator, kobj):
            order.append("sync")
            return None

        @KnowledgeHandler.create(HandlerType.Bundle)
        async def async_second(coordinator, kobj):
            order.append("async")
            return None

        pipeline = KnowledgePipeline(default_handlers=[sync_first, async_second])
        kobj = KnowledgeObject(rid="orn:test:x")
        await pipeline.call_handler_chain(HandlerType.Bundle, kobj)
        assert order == ["sync", "async"]


# ===========================================================================
# Pipeline process() — 5-phase execution
# ===========================================================================

class TestPipelineProcess:
    async def test_phases_execute_in_order(self):
        order = []

        def make_handler(phase: HandlerType):
            @KnowledgeHandler.create(phase)
            def h(coordinator, kobj):
                order.append(phase.value)
                return None
            return h

        handlers = [make_handler(p) for p in KnowledgePipeline.PHASE_ORDER]
        pipeline = KnowledgePipeline(default_handlers=handlers)
        kobj = KnowledgeObject(rid="orn:test:x")
        await pipeline.process(kobj)
        assert order == ["rid", "manifest", "bundle", "network", "final"]

    async def test_handler_returning_none_keeps_kobj(self):
        @KnowledgeHandler.create(HandlerType.RID)
        def noop(coordinator, kobj):
            return None

        pipeline = KnowledgePipeline(default_handlers=[noop])
        kobj = KnowledgeObject(rid="orn:test:x", event_type="NEW")
        result = await pipeline.process(kobj)
        assert result.rid == "orn:test:x"
        assert result.event_type == "NEW"

    async def test_handler_returning_modified_kobj_updates_downstream(self):
        @KnowledgeHandler.create(HandlerType.RID)
        def modifier(coordinator, kobj):
            kobj.result_status = "modified"
            return kobj

        @KnowledgeHandler.create(HandlerType.Bundle)
        def checker(coordinator, kobj):
            assert kobj.result_status == "modified"
            kobj.result_status = "checked"
            return kobj

        pipeline = KnowledgePipeline(default_handlers=[modifier, checker])
        kobj = KnowledgeObject(rid="orn:test:x")
        result = await pipeline.process(kobj)
        assert result.result_status == "checked"

    async def test_stop_chain_halts_pipeline(self):
        order = []

        @KnowledgeHandler.create(HandlerType.RID)
        def stopper(coordinator, kobj):
            order.append("rid")
            kobj.result_status = "stopped"
            return STOP_CHAIN

        @KnowledgeHandler.create(HandlerType.Bundle)
        def never_reached(coordinator, kobj):
            order.append("bundle")
            return None

        pipeline = KnowledgePipeline(default_handlers=[stopper, never_reached])
        kobj = KnowledgeObject(rid="orn:test:x")
        result = await pipeline.process(kobj)

        assert isinstance(result, PipelineStop)
        assert result.kobj.result_status == "stopped"
        assert order == ["rid"]  # Bundle handler never called

    async def test_pipeline_returns_final_kobj_with_status(self):
        @KnowledgeHandler.create(HandlerType.Network)
        def success_handler(coordinator, kobj):
            kobj.result_status = "success"
            return kobj

        pipeline = KnowledgePipeline(default_handlers=[success_handler])
        kobj = KnowledgeObject(rid="orn:test:x")
        result = await pipeline.process(kobj)
        assert not isinstance(result, PipelineStop)
        assert result.result_status == "success"

    async def test_pipeline_does_not_write_cache(self):
        """Pipeline itself does NOT write to cache — only koi_node.handle_event does."""
        mock_coordinator = MagicMock()
        mock_coordinator.koi_node = MagicMock()

        @KnowledgeHandler.create(HandlerType.Network)
        def emit(coordinator, kobj):
            kobj.result_status = "success"
            return kobj

        pipeline = KnowledgePipeline(coordinator=mock_coordinator, default_handlers=[emit])
        kobj = KnowledgeObject(rid="orn:test:x")
        await pipeline.process(kobj)

        # No cache writes on coordinator or koi_node
        mock_coordinator.koi_node.cache_bundle.assert_not_called()

    async def test_stop_chain_preserves_mutations(self):
        """PipelineStop.kobj is the deep-copied kobj the handler mutated."""
        @KnowledgeHandler.create(HandlerType.Bundle)
        def dedup(coordinator, kobj):
            kobj.result_status = "skipped_duplicate"
            kobj.contents = {"dedup": True}
            return STOP_CHAIN

        pipeline = KnowledgePipeline(default_handlers=[dedup])
        kobj = KnowledgeObject(rid="orn:test:x")
        result = await pipeline.process(kobj)

        assert isinstance(result, PipelineStop)
        assert result.kobj.result_status == "skipped_duplicate"
        assert result.kobj.contents == {"dedup": True}
        # Original kobj not mutated
        assert kobj.result_status is None
