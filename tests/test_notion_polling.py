"""Notion polling contracts; synthetic HTTP only, no workspace credentials."""
import asyncio
import copy
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from sensors.notion.notion_sensor import NotionKOISensor, PIIFilter
from shared.persistent_state import PersistentSensorState
from koi_protocol.core.bundle_system import document_to_bundle

PAGE = '11111111-1111-4111-8111-111111111111'
BLOCK = '22222222-2222-4222-8222-222222222222'
NESTED = '33333333-3333-4333-8333-333333333333'
COMMENT = '44444444-4444-4444-8444-444444444444'
USER = '55555555-5555-4555-8555-555555555555'
THREAD = '66666666-6666-4666-8666-666666666666'


def rich(text):
    return [{'type': 'text', 'plain_text': text, 'text': {'content': text}}]


def page(status='Todo'):
    return {'id': PAGE, 'url': 'https://www.notion.so/' + PAGE.replace('-', ''),
            'created_time': '2026-09-01T00:00:00Z', 'last_edited_time': '2026-09-08T00:00:00Z',
            'created_by': {'id': USER, 'name': 'Reviewer'},
            'properties': {'Name': {'type': 'title', 'title': rich('A card')},
                           'Status': {'type': 'status', 'status': {'id': 's', 'name': status}}}}


def comment(comment_id=COMMENT, text='Proposed change', edited='2026-09-08T00:00:00Z'):
    return {'id': comment_id, 'discussion_id': THREAD, 'parent': {'type': 'block_id', 'block_id': BLOCK},
            'created_by': {'id': USER, 'name': 'Reviewer', 'person': {'email': 'secret@example.org'}},
            'created_time': '2026-09-01T00:00:00Z', 'last_edited_time': edited, 'rich_text': rich(text)}


def listing(results, cursor=None):
    return {'results': results, 'has_more': cursor is not None, 'next_cursor': cursor}


class Response:
    def __init__(self, data, status=200):
        self.data, self.status = data, status
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def json(self):
        return copy.deepcopy(self.data)
    async def text(self):
        return json.dumps(self.data)


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
    def get(self, url, params=None, **kwargs):
        key = (url.split('/v1/')[-1], (params or {}).get('start_cursor'))
        self.calls.append((key, copy.deepcopy(params)))
        target_key = (key[0], (params or {}).get('block_id'), key[1])
        value = self.routes[target_key] if target_key in self.routes else self.routes[key]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, Response) else Response(value)

    def post(self, url, json=None, **kwargs):
        return self.get(url, params=json, **kwargs)


@pytest.fixture
def sensor(tmp_path):
    # No KOI node identity/cache or sensor state is created in the checkout.
    s = NotionKOISensor.__new__(NotionKOISensor)
    s.workspace_id = 'test'
    s.is_private = True
    s.access_source = 'notion-test'
    s.pii_filter = PIIFilter()
    s.skip_pages = set()
    s.skip_sections = []
    s.monitored_databases = {'db': {'title': 'Board', 'check_interval': 0, 'last_checked': None}}
    s.monitored_pages = {}
    s.state = PersistentSensorState('notion', tmp_path)
    s.koi_node = type('Node', (), {'emit_new_event': AsyncMock(return_value=True),
                                 'emit_update_event': AsyncMock(return_value=True)})()
    s.max_pages_per_poll = 25
    s.max_block_requests = 100
    s.max_api_pages = 100
    s.request_interval = 0
    s._last_api_request = 0
    s.video_transcriber = type('Video', (), {'enabled': False})()
    s.query_database = AsyncMock(return_value=[page()])
    s.get_user = AsyncMock(return_value={'id': USER, 'name': 'Reviewer'})
    s.session = Session({('blocks/' + PAGE + '/children', None): listing([]),
                         ('comments', None): listing([])})
    return s


def run(coro):
    return asyncio.run(coro)


def test_property_only_change_is_delivered(sensor):
    first = run(sensor.check_for_changes())
    run(sensor.send_to_coordinator(first))
    sensor.query_database.return_value = [page('Done')]
    second = run(sensor.check_for_changes())
    assert len(second) == 1
    assert second[0]['event_type'] == 'UPDATE'
    assert second[0]['metadata']['properties']['Status'] == 'Done'


def test_comments_are_independent_records_and_refresh_without_page_edits(sensor):
    sensor.session.routes[('comments', None)] = listing([comment()])
    first = run(sensor.check_for_changes())
    comments = [x for x in first if x['metadata'].get('comment_id')]
    assert len(comments) == 1
    c = comments[0]
    assert c['metadata']['discussion_id'] == THREAD
    assert c['metadata']['record_kind'] == 'comment'
    assert c['metadata']['author_id'] == USER
    assert c['metadata']['is_private'] is True
    bundle = document_to_bundle(c)
    assert str(bundle.rid).startswith('orn:notion.comment:')
    assert str(bundle.rid) != str(document_to_bundle(next(d for d in first if d['metadata']['record_kind'] == 'page')).rid)
    assert bundle.manifest.metadata['is_private'] is True
    run(sensor.send_to_coordinator(first))
    assert run(sensor.check_for_changes()) == []
    sensor.session.routes[('comments', None)] = listing([comment(text='Updated proposal', edited='2026-09-08T01:00:00Z')])
    changes = run(sensor.check_for_changes())
    assert len(changes) == 1 and changes[0]['metadata']['comment_id'] == COMMENT
    assert changes[0]['event_type'] == 'UPDATE'
    assert 'Updated proposal' in changes[0]['content']


def block(block_id=BLOCK, kind='paragraph', text='Body', children=False):
    return {'id': block_id, 'type': kind, 'has_children': children,
            'last_edited_time': '2026-09-08T00:00:00Z', kind: {'rich_text': rich(text)}}


def comment_docs(documents):
    return [doc for doc in documents if doc['metadata']['record_kind'] == 'comment']


def test_nested_block_and_comment_pagination_deduplicate_comment_id(sensor):
    sensor.session.routes.update({
        ('blocks/' + PAGE + '/children', None): listing([block(children=True)], 'next-block'),
        ('blocks/' + PAGE + '/children', 'next-block'): listing([block(USER, text='Second')]),
        ('blocks/' + BLOCK + '/children', None): listing([block(NESTED, text='Nested')]),
        ('comments', NESTED, None): listing([comment()], 'next-comment'),
        ('comments', NESTED, 'next-comment'): listing([comment(text='Latest', edited='2026-09-08T02:00:00Z')]),
    })
    changes = run(sensor.check_for_changes())
    assert len(comment_docs(changes)) == 1
    doc = comment_docs(changes)[0]
    assert 'Latest' in doc['content']
    assert doc['metadata']['parent'] == {'type': 'block_id', 'block_id': BLOCK}
    assert doc['url'].endswith('#' + BLOCK.replace('-', ''))
    parent = next(d for d in changes if d['metadata']['record_kind'] == 'page')
    assert parent['content'] == 'Body\n\nNested\n\nSecond'
    assert parent['metadata']['comment_coverage']['targets_checked'] == 4
    run(sensor.send_to_coordinator(changes))
    assert run(sensor.check_for_changes()) == []


def test_new_comment_without_page_or_body_edit(sensor):
    run(sensor.send_to_coordinator(run(sensor.check_for_changes())))
    sensor.session.routes[('comments', None)] = listing([comment()])
    changes = run(sensor.check_for_changes())
    assert len(changes) == 1
    assert changes[0]['event_type'] == 'NEW'
    assert changes[0]['metadata']['comment_id'] == COMMENT
    assert sensor.query_database.call_args.kwargs == {}  # No last_edited filter.


@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
def test_comment_api_failure_preserves_pending_without_false_empty_or_delete(sensor, status):
    sensor.session.routes[('comments', None)] = listing([comment()])
    first = run(sensor.check_for_changes())
    sensor.koi_node.emit_new_event.return_value = False
    run(sensor.send_to_coordinator(first))
    pending_hash = sensor._poll_state('notion_outbox_v1')['comment:' + COMMENT]['content_hash']
    sensor.session.routes[('comments', None)] = Response({'code': 'restricted_resource'}, status)
    changes = run(sensor.check_for_changes())
    assert comment_docs(changes) == []
    assert sensor._poll_state('notion_outbox_v1')['comment:' + COMMENT]['content_hash'] == pending_hash
    coverage = changes[0]['metadata']['comment_coverage']
    assert coverage['status'] == 'partial'
    assert coverage['errors'][0]['status'] == status
    assert coverage['resolved_history_available'] is False
    assert all(d['event_type'] in {'NEW', 'UPDATE'} for d in changes)


@pytest.mark.parametrize('target', ['pages', 'blocks'])
def test_revoked_page_or_body_access_holds_all_pending(sensor, target):
    first = run(sensor.check_for_changes())
    sensor.monitored_databases['db']['check_interval'] = 3600
    key = ('pages/' + PAGE, None) if target == 'pages' else ('blocks/' + PAGE + '/children', None)
    sensor.session.routes[('pages/' + PAGE, None)] = page()
    sensor.session.routes[key] = Response({'code': 'restricted_resource'}, 403)
    assert run(sensor.check_for_changes()) == []
    assert PAGE in sensor._poll_state('notion_outbox_v1')
    coverage = sensor._poll_state('notion_poll_coverage_v1')[PAGE]
    assert coverage['error']['status'] == 403
    assert coverage['deletion_inferred'] is False
    assert first[0]['content_hash'] == sensor._poll_state('notion_outbox_v1')[PAGE]['content_hash']


def test_pending_absent_or_unscanned_comment_is_held_until_positively_observed(sensor):
    sensor.max_comment_targets = 2
    sensor.session.routes.update({
        ('blocks/' + PAGE + '/children', None): listing([block(BLOCK), block(NESTED)]),
        ('comments', BLOCK, None): listing([comment()]),
        ('comments', NESTED, None): listing([]),
    })
    first = run(sensor.check_for_changes())
    assert len(comment_docs(first)) == 1  # Leave it pending (coordinator unavailable).
    assert comment_docs(run(sensor.check_for_changes())) == []  # BLOCK skipped this visit.
    sensor.session.routes[('comments', BLOCK, None)] = listing([])
    assert comment_docs(run(sensor.check_for_changes())) == []  # Absent is not resolution.
    assert 'comment:' + COMMENT in sensor._poll_state('notion_outbox_v1')
    run(sensor.check_for_changes())  # NESTED visit
    sensor.session.routes[('comments', BLOCK, None)] = listing([comment(text='Current version')])
    retried = comment_docs(run(sensor.check_for_changes()))
    assert len(retried) == 1 and 'Current version' in retried[0]['content']


def test_source_revert_cancels_superseded_failed_update(sensor):
    run(sensor.send_to_coordinator(run(sensor.check_for_changes())))  # A acknowledged.
    sensor.query_database.return_value = [page('Done')]
    sensor.koi_node.emit_update_event.return_value = False
    run(sensor.send_to_coordinator(run(sensor.check_for_changes())))  # B not acknowledged.
    assert PAGE in sensor._poll_state('notion_outbox_v1')
    sensor.query_database.return_value = [page()]
    assert run(sensor.check_for_changes()) == []  # A again: must never send cached B.
    assert PAGE not in sensor._poll_state('notion_outbox_v1')


def test_workspace_hashes_outbox_and_rids_are_isolated(sensor):
    sensor.session.routes[('comments', None)] = listing([comment()])
    first = run(sensor.check_for_changes())
    first_rids = {str(document_to_bundle(d).rid) for d in first}
    run(sensor.send_to_coordinator(first))
    assert run(sensor.check_for_changes()) == []
    sensor.workspace_id = 'other'
    second = run(sensor.check_for_changes())
    assert len(second) == 2
    assert all(d['event_type'] == 'NEW' for d in second)
    assert first_rids.isdisjoint({str(document_to_bundle(d).rid) for d in second})
    assert set(sensor.state.metadata['notion_document_hashes_v1']) == {'test', 'other'}


def test_durable_scan_queue_progresses_between_discovery_intervals_and_after_restart(sensor):
    pages = []
    for n in range(7):
        p = page()
        p['id'] = f'aaaaaaaa-aaaa-4aaa-8aaa-{n:012d}'
        pages.append(p)
        sensor.session.routes[('pages/' + p['id'], None)] = p
        sensor.session.routes[('blocks/' + p['id'] + '/children', None)] = listing([])
    sensor.monitored_databases['db']['check_interval'] = 3600
    sensor.query_database.return_value = pages
    sensor.max_pages_per_poll = 2
    seen = set()
    for _ in range(4):
        changes = run(sensor.check_for_changes())
        assert len(changes) <= 2
        seen.update(d['metadata']['page_id'] for d in changes)
        run(sensor.send_to_coordinator(changes))
        sensor.state = PersistentSensorState('notion', sensor.state.state_file.parent)
    assert seen == {p['id'] for p in pages}
    assert sensor.query_database.call_count == 1


def test_no_due_database_does_not_reset_scan_position(sensor):
    sensor.monitored_databases['db']['check_interval'] = 3600
    sensor._poll_state('notion_page_cursor_v1')['queue'] = [PAGE, BLOCK]
    sensor._poll_state('notion_database_pages_v1')['db'] = [PAGE, BLOCK]
    sensor.monitored_databases['db']['last_checked'] = datetime.now(timezone.utc)
    sensor.session.routes[('pages/' + PAGE, None)] = page()
    p = page(); p['id'] = BLOCK
    sensor.session.routes[('pages/' + BLOCK, None)] = p
    sensor.session.routes[('blocks/' + BLOCK + '/children', None)] = listing([])
    sensor.max_pages_per_poll = 1
    assert run(sensor.check_for_changes())[0]['metadata']['page_id'] == PAGE
    assert run(sensor.check_for_changes())[0]['metadata']['page_id'] == BLOCK


def test_coordinator_failure_survives_restart_and_retries_fresh_source(sensor):
    first = run(sensor.check_for_changes())
    sensor.koi_node.emit_new_event.side_effect = RuntimeError('synthetic disconnect')
    run(sensor.send_to_coordinator(first))
    sensor.state = PersistentSensorState('notion', sensor.state.state_file.parent)
    assert sensor._poll_state('notion_document_hashes_v1') == {}
    assert PAGE in sensor._poll_state('notion_outbox_v1')
    sensor.monitored_databases['db']['check_interval'] = 3600
    sensor.session.routes[('pages/' + PAGE, None)] = page('Fresh')
    sensor.koi_node.emit_new_event.side_effect = None
    retry = run(sensor.check_for_changes())
    assert retry[0]['metadata']['properties']['Status'] == 'Fresh'
    run(sensor.send_to_coordinator(retry))
    sensor.state = PersistentSensorState('notion', sensor.state.state_file.parent)
    assert sensor._poll_state('notion_outbox_v1') == {}
    assert sensor._poll_state('notion_document_hashes_v1')[PAGE] == retry[0]['content_hash']
    assert run(sensor.check_for_changes()) == []


def test_coordinator_http_non_2xx_is_not_acknowledged(sensor):
    import logging
    from unittest.mock import Mock
    from koi_protocol.nodes.koi_node import KOIPartialNode
    node = KOIPartialNode.__new__(KOIPartialNode)
    node.node_id = 'test-node'
    node.coordinator_url = 'http://synthetic.invalid'
    node.logger = logging.getLogger('notion-test')
    node.envelope_sign = False
    node.queue_event = Mock()
    node.session = type('CoordinatorHTTP', (), {'post': lambda *a, **k: Response({}, 503)})()
    sensor.koi_node = node
    changes = run(sensor.check_for_changes())
    run(sensor.send_to_coordinator(changes))
    assert sensor._poll_state('notion_document_hashes_v1') == {}
    assert PAGE in sensor._poll_state('notion_outbox_v1')
    assert not sensor.state.pending.get(sensor.workspace_id)


def test_people_relations_paginate_and_contact_data_is_filtered_before_queue(sensor):
    p = page('Email status@example.org')
    p['properties']['Owner'] = {'type': 'people', 'id': 'p%3Aid', 'people': [{'id': USER}] * 25}
    p['properties']['Related'] = {'type': 'relation', 'id': 'rel', 'has_more': True, 'relation': [{'id': PAGE}]}
    p['properties']['Email'] = {'type': 'email', 'email': 'private@example.org'}
    p['properties']['Phone'] = {'type': 'phone_number', 'phone_number': '+1 555 123 4567'}
    p['properties']['Name']['title'] = rich('A title@private.org')
    person = {'id': USER, 'name': 'Name person@example.org', 'person': {'email': 'hidden@example.org'}, 'avatar_url': 'https://secret.invalid/avatar'}
    sensor.query_database.return_value = [p]
    c = comment(text='Email me@private.org or call +1 555 123 4567')
    c['created_by'] = person
    c['rich_text'].append({'type': 'mention', 'plain_text': 'Mention mention@private.org'})
    c['attachments'] = [{'file': {'url': 'https://secret.invalid/signed'}}]
    sensor.session.routes.update({
        ('comments', None): listing([c]),
        ('pages/' + PAGE + '/properties/p%3Aid', None): listing([{'type': 'people', 'people': person}], 'owner-next'),
        ('pages/' + PAGE + '/properties/p%3Aid', 'owner-next'): listing([{'type': 'people', 'people': {'id': BLOCK}}]),
        ('pages/' + PAGE + '/properties/rel', None): listing([{'type': 'relation', 'relation': {'id': PAGE}}], 'rel-next'),
        ('pages/' + PAGE + '/properties/rel', 'rel-next'): listing([{'type': 'relation', 'relation': {'id': BLOCK}}]),
    })
    changes = run(sensor.check_for_changes())
    parent = next(d for d in changes if d['metadata']['record_kind'] == 'page')
    props = parent['metadata']['properties']
    assert props['Related'] == sorted([PAGE, BLOCK])  # IDs must not be mistaken for phone numbers.
    assert props['Owner'] == sorted([{'id': USER, 'name': 'Name [REDACTED_EMAIL]'}, {'id': BLOCK}], key=lambda p: p['id'])
    assert 'Email' not in props and 'Phone' not in props
    assert props['Status'] == 'Email [REDACTED_EMAIL]'
    assert 'Mention [REDACTED_EMAIL]' in comment_docs(changes)[0]['content']
    stored = sensor.state.state_file.read_text()
    for secret in ['@private.org', '@example.org', 'secret.invalid', '+1 555 123 4567', 'avatar_url']:
        assert secret not in stored
    assert comment_docs(changes)[0]['metadata']['author_id'] == USER


def test_partial_property_or_block_read_never_replaces_complete_snapshot(sensor):
    run(sensor.send_to_coordinator(run(sensor.check_for_changes())))
    original = sensor._poll_state('notion_document_hashes_v1')[PAGE]
    p = page(); p['properties']['Related'] = {'type': 'relation', 'id': 'rel', 'has_more': True, 'relation': []}
    sensor.query_database.return_value = [p]
    sensor.session.routes[('pages/' + PAGE + '/properties/rel', None)] = Response({}, 403)
    assert run(sensor.check_for_changes()) == []
    assert sensor._poll_state('notion_document_hashes_v1')[PAGE] == original
    sensor.query_database.return_value = [page()]
    sensor.session.routes[('blocks/' + PAGE + '/children', None)] = listing([block()], 'denied')
    sensor.session.routes[('blocks/' + PAGE + '/children', 'denied')] = Response({}, 403)
    assert run(sensor.check_for_changes()) == []
    assert sensor._poll_state('notion_document_hashes_v1')[PAGE] == original


def test_database_query_paginates_and_rejects_partial_or_cyclic_cursor(sensor):
    sensor.query_database = NotionKOISensor.query_database.__get__(sensor)
    sensor.session.routes[('databases/db/query', None)] = listing([page()], 'next')
    p = page(); p['id'] = BLOCK
    sensor.session.routes[('databases/db/query', 'next')] = listing([p])
    assert len(run(sensor.query_database('db'))) == 2
    sensor.session.routes[('databases/db/query', 'next')] = listing([p], 'next')
    from sensors.notion.notion_sensor import NotionFetchError
    with pytest.raises(NotionFetchError, match='invalid_cursor'):
        run(sensor.query_database('db'))
    sensor.session.routes[('databases/db/query', 'next')] = Response({}, 403)
    with pytest.raises(NotionFetchError) as exc:
        run(sensor.query_database('db'))
    assert exc.value.status == 403


def test_unchanged_video_not_retranscribed_on_comment_poll_but_edit_refreshes(sensor):
    sensor.video_transcriber.enabled = True
    sensor.video_transcriber.transcribe_video_url = AsyncMock(return_value='Transcript person@example.org')
    video = block(BLOCK, 'video')
    video['video'] = {'type': 'file', 'file': {'url': 'https://secret.invalid/signed'}, 'caption': []}
    sensor.session.routes[('blocks/' + PAGE + '/children', None)] = listing([video])
    run(sensor.send_to_coordinator(run(sensor.check_for_changes())))
    sensor.session.routes[('comments', None)] = listing([comment()])
    changes = run(sensor.check_for_changes())
    assert len(changes) == 1 and changes[0]['metadata']['record_kind'] == 'comment'
    assert sensor.video_transcriber.transcribe_video_url.await_count == 1
    video['last_edited_time'] = '2026-09-08T01:00:00Z'
    sensor.session.routes[('blocks/' + PAGE + '/children', None)] = listing([video])
    run(sensor.check_for_changes())
    assert sensor.video_transcriber.transcribe_video_url.await_count == 2
    stored = sensor.state.state_file.read_text()
    assert 'person@example.org' not in stored and 'secret.invalid/signed' not in stored


def test_excluded_section_does_not_reopen_at_heading_inside_excluded_subtree(sensor):
    sensor.skip_sections = ['private section']
    sensor.session.routes.update({
        ('blocks/' + PAGE + '/children', None): listing([
            block(BLOCK, 'heading_1', 'Private Section'),
            block(NESTED, 'toggle', 'Hidden', children=True),
            block(USER, 'heading_1', 'Public Section'),
            block(THREAD, 'paragraph', 'Allowed body'),
        ]),
        ('blocks/' + NESTED + '/children', None): listing([
            block(COMMENT, 'heading_2', 'A nested heading'),
            block('secret-block', text='Hidden secret body'),
        ]),
        ('comments', 'secret-block', None): listing([comment(text='Hidden secret comment')]),
    })
    changes = run(sensor.check_for_changes())
    assert comment_docs(changes) == []
    parent = next(d for d in changes if d['metadata']['record_kind'] == 'page')
    assert 'Hidden' not in parent['content'] and 'Allowed body' in parent['content']
    queried_targets = [params['block_id'] for key, params in sensor.session.calls if key[0] == 'comments']
    assert NESTED not in queried_targets and 'secret-block' not in queried_targets


def test_skipped_page_block_is_not_traversed_or_queried_for_comments(sensor):
    sensor.skip_pages = {BLOCK.replace('-', '')}
    sensor.session.routes[('blocks/' + PAGE + '/children', None)] = listing([block(children=True)])
    changes = run(sensor.check_for_changes())
    parent = next(d for d in changes if d['metadata']['record_kind'] == 'page')
    assert parent['content'] == ''
    assert parent['metadata']['comment_coverage']['targets_total'] == 1


def test_comment_pagination_failure_does_not_emit_partial_target(sensor):
    sensor.session.routes[('comments', None)] = listing([comment()], 'next')
    sensor.session.routes[('comments', 'next')] = Response({}, 403)
    changes = run(sensor.check_for_changes())
    assert comment_docs(changes) == []
    assert changes[0]['metadata']['comment_coverage']['status'] == 'partial'
    assert 'comment:' + COMMENT not in sensor._poll_state('notion_outbox_v1')


def test_list_budget_failure_is_explicit_and_cannot_emit_empty_snapshot(sensor):
    sensor.max_api_pages = 1
    sensor.session.routes[('blocks/' + PAGE + '/children', None)] = listing([block()], 'next')
    assert run(sensor.check_for_changes()) == []
    coverage = sensor._poll_state('notion_poll_coverage_v1')[PAGE]
    assert coverage['error']['code'] == 'pagination_budget_exhausted'
    assert coverage['deletion_inferred'] is False


def test_explicit_page_without_hyphens_uses_api_canonical_identity(sensor):
    sensor.monitored_databases = {}
    sensor.monitored_pages = {PAGE.replace('-', ''): {'title': 'Card'}}
    sensor.session.routes[('pages/' + PAGE.replace('-', ''), None)] = page()
    changes = run(sensor.check_for_changes())
    assert len(changes) == 1 and changes[0]['state_key'] == PAGE
    run(sensor.send_to_coordinator(changes))
    assert run(sensor.check_for_changes()) == []


def test_child_page_is_a_separate_source_not_an_ancestor_comment_target(sensor):
    sensor.session.routes[('blocks/' + PAGE + '/children', None)] = listing([
        block(BLOCK, 'child_page', children=True)])
    sensor.session.routes[('comments', BLOCK, None)] = listing([comment()])
    changes = run(sensor.check_for_changes())
    assert comment_docs(changes) == []
    parent = changes[0]
    assert parent['metadata']['comment_coverage']['child_references_excluded'] == 1
    assert parent['metadata']['comment_coverage']['targets_total'] == 1
    assert ('blocks/' + BLOCK + '/children', None) not in [key for key, _ in sensor.session.calls]
    # Explicitly monitoring the child attributes its comments to that source.
    child = page(); child['id'] = BLOCK
    sensor.monitored_pages = {BLOCK: {}}
    sensor.session.routes[('pages/' + BLOCK, None)] = child
    sensor.session.routes[('blocks/' + BLOCK + '/children', None)] = listing([])
    observed = comment_docs(run(sensor.check_for_changes()))
    assert len(observed) == 1 and observed[0]['metadata']['page_id'] == BLOCK


def test_comment_protocol_and_persistent_cache_roundtrip(sensor, tmp_path):
    from koi_protocol.core.rid_system import RID
    from koi_protocol.core.bundle_system import KOIEvent
    from koi_protocol.core.persistent_cache import PersistentBundleCache
    sensor.session.routes[('comments', None)] = listing([comment()])
    doc = comment_docs(run(sensor.check_for_changes()))[0]
    bundle = document_to_bundle(doc)
    event = KOIEvent.from_dict(KOIEvent.new_event(bundle, 'test-node').to_dict())
    assert str(event.rid) == str(RID.parse(doc['rid']))
    assert event.bundle.contents['metadata']['comment_id'] == COMMENT
    cache = PersistentBundleCache(str(tmp_path / 'bundles'))
    cache.write(event.bundle)
    restored = PersistentBundleCache(str(tmp_path / 'bundles')).read(event.rid)
    assert restored.contents == event.bundle.contents
    assert restored.manifest.sha256_hash == event.bundle.manifest.sha256_hash
    # This asserts stored source ACL fields, not downstream authorization behavior.
    assert restored.contents['metadata']['is_private'] is True
    assert restored.contents['metadata']['access_source'] == sensor.access_source
