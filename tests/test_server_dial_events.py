"""Tests for the `/api/v0/dial/events` Server-Sent Events stream of dial state.

HTTP tests drive real streams against fake handler and config objects; unit tests cover
push_dials, the module helpers, the periodic tick and the image revision counter.
"""
import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock

import pytest
import tornado.testing
import tornado.web
from tornado.concurrent import Future
from tornado.tcpclient import TCPClient

import server
from server import Dial_Get_Events, dial_delivery_state, public_dial_state, push_dial_events
from server_dial_handler import ServerDialHandler

ALLOWED = 'ABCDEF'
DENIED = 'FED210'

EVENTS_PATH = '/api/v0/dial/events'
LIST_ITEM_KEYS = ['uid', 'dial_name', 'value', 'backlight', 'image_file']
EVENT_ITEM_KEYS = LIST_ITEM_KEYS + ['image_rev', 'value_delivery', 'backlight_delivery']


def make_dial(name, **overrides):
    dial = {
        'dial_name': name,
        'value': 0,
        'index': 0,
        'backlight': {'red': 0, 'green': 0, 'blue': 0, 'white': 0},
        'image_file': f'/srv/upload/img_{name}',
        'value_changed': False,
        'backlight_changed': False,
        'value_fail_count': 0,
        'backlight_fail_count': 0,
        'value_retry_after': 0,
        'backlight_retry_after': 0,
        'value_unresponsive': False,
        'backlight_unresponsive': False,
        'image_changed': False,
        'easing': {'dial_step': 5, 'dial_period': 50, 'backlight_step': 5, 'backlight_period': 50},
        'fw_version': 'v1.0',
        'update_deadline': 0.0,
    }
    dial.update(overrides)
    return dial


def expected_item(uid, dial, image_rev=0, value_delivery='delivered', backlight_delivery='delivered'):
    """The exact `dials` event item for one dial, keys in wire order."""
    return {
        'uid': uid,
        'dial_name': dial['dial_name'],
        'value': dial['value'],
        'backlight': {k: v for k, v in dial['backlight'].items() if k != 'white'},
        'image_file': dial['image_file'],
        'image_rev': image_rev,
        'value_delivery': value_delivery,
        'backlight_delivery': backlight_delivery,
    }


class FakeDialHandler: # pylint: disable=too-few-public-methods
    def __init__(self, dials):
        self.dials = dials
        self.image_revision = {}

    def get_dial_info(self, dial_uid=None):
        if dial_uid is not None:
            return self.dials.get(dial_uid, None)
        return self.dials


class FakeConfig:
    def __init__(self):
        # None grants every dial.
        self.keys = {'scopedkey': {ALLOWED}, 'adminkey': None, 'emptykey': set()}

    def is_valid_api_key(self, key):
        return key in self.keys

    def api_key_has_access_to_dial(self, key, uid):
        if key not in self.keys:
            return False
        grants = self.keys[key]
        return grants is None or uid in grants


def parse_events(raw):
    """Parse the complete blocks of an SSE body into [(event, data)], skipping `:` comment lines.

    @param raw: response body bytes; a trailing incomplete block is ignored.
    @returns: list of (event name, decoded JSON data) tuples.
    """
    events = []
    for block in raw.decode('utf-8').split('\n\n')[:-1]:
        lines = [line for line in block.split('\n') if not line.startswith(':')]
        if not lines:
            continue
        assert len(lines) == 2, f'malformed block {block!r}'
        assert lines[0].startswith('event: ') and lines[1].startswith('data: '), f'malformed block {block!r}'
        events.append((lines[0][len('event: '):], json.loads(lines[1][len('data: '):])))
    return events


class DialEventsHTTPTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.dials = {ALLOWED: make_dial('Allowed', value=10), DENIED: make_dial('Denied', value=20)}
        self.fake_handler = FakeDialHandler(self.dials)
        self.fake_config = FakeConfig()
        self.streams = set()
        return tornado.web.Application([
            (EVENTS_PATH, Dial_Get_Events,
             {'handler': self.fake_handler, 'config': self.fake_config, 'streams': self.streams}),
        ])

    def _open(self, key):
        chunks = []
        fut = self.http_client.fetch(self.get_url(f'{EVENTS_PATH}?key={key}'),
                                     streaming_callback=chunks.append, raise_error=False)
        return fut, chunks

    @staticmethod
    def _events(chunks):
        return parse_events(b''.join(chunks))

    async def _until(self, cond, timeout=2.0):
        deadline = time.monotonic() + timeout
        while not cond():
            if time.monotonic() >= deadline:
                raise AssertionError(f'condition not met within {timeout} s')
            await asyncio.sleep(0.01)

    def _tick(self):
        push_dial_events(self.streams)

    async def _end(self, fut):
        for stream in list(self.streams):
            stream.end_stream()
        return await fut

    async def _open_and_wait(self, key):
        fut, chunks = self._open(key)
        await self._until(lambda: len(self._events(chunks)) == 1)
        return fut, chunks

    async def _tick_and_wait(self, chunks, count):
        self._tick()
        await self._until(lambda: len(self._events(chunks)) == count)
        return self._events(chunks)[-1]

    def _assert_json_401(self, path):
        # A handler that keeps going after its 401 logs an error instead of changing the response.
        with self.assertNoLogs('tornado.application', level='ERROR'):
            response = self.fetch(path)
        assert response.code == 401
        assert response.headers['Content-Type'].startswith('application/json')
        assert 'Cache-Control' not in response.headers
        assert json.loads(response.body) == {'status': 'fail', 'message': 'Unauthorized', 'data': None}
        assert not self.streams

    def test_missing_key_gets_json_401(self):
        self._assert_json_401(EVENTS_PATH)

    def test_unknown_key_gets_json_401(self):
        self._assert_json_401(f'{EVENTS_PATH}?key=nope')

    def test_failed_first_push_leaves_no_subscriber(self):
        def broken(dial_uid=None):
            raise KeyError('dial_name')
        self.fake_handler.get_dial_info = broken

        with self.assertLogs('tornado.application', level='ERROR'):
            response = self.fetch(f'{EVENTS_PATH}?key=scopedkey')
        assert response.code == 500
        assert not self.streams

    @tornado.testing.gen_test(timeout=5)
    async def test_stream_response_headers(self):
        fut, chunks = await self._open_and_wait('scopedkey')
        response = await self._end(fut)

        assert response.code == 200
        assert response.headers['Content-Type'] == 'text/event-stream'
        assert response.headers['Cache-Control'] == 'no-cache'
        assert response.headers['Access-Control-Allow-Origin'] == '*'
        assert response.headers['Transfer-Encoding'] == 'chunked'
        assert 'Content-Length' not in response.headers
        assert 'Etag' not in response.headers
        body = b''.join(chunks).decode('utf-8')
        assert '\r' not in body
        for line in body.split('\n'):
            if line:
                assert line.startswith(('event: ', 'data: ', ':')), f'unexpected field line {line!r}'

    @tornado.testing.gen_test(timeout=5)
    async def test_first_event_is_snapshot_of_accessible_dials(self):
        fut, chunks = await self._open_and_wait('scopedkey')

        expected = {'dials': [expected_item(ALLOWED, self.dials[ALLOWED])]}
        assert self._events(chunks) == [('dials', expected)]
        assert list(self._events(chunks)[0][1]['dials'][0]) == EVENT_ITEM_KEYS
        compact = json.dumps(expected, separators=(',', ':'))
        assert b''.join(chunks) == f'event: dials\ndata: {compact}\n\n'.encode('utf-8')
        assert not fut.done()
        assert len(self.streams) == 1
        await self._end(fut)

    @tornado.testing.gen_test(timeout=5)
    async def test_admin_key_sees_every_dial_in_handler_order(self):
        # Reverse of sorted order, so sorting the uids shows.
        self.fake_handler.dials = {DENIED: self.dials[DENIED], ALLOWED: self.dials[ALLOWED]}
        fut, chunks = await self._open_and_wait('adminkey')

        assert self._events(chunks) == [('dials', {'dials': [
            expected_item(DENIED, self.dials[DENIED]),
            expected_item(ALLOWED, self.dials[ALLOWED]),
        ]})]
        await self._end(fut)

    @tornado.testing.gen_test(timeout=5)
    async def test_key_without_dials_gets_empty_snapshot(self):
        fut, chunks = await self._open_and_wait('emptykey')

        assert self._events(chunks) == [('dials', {'dials': []})]
        assert not fut.done()
        await self._end(fut)

    @tornado.testing.gen_test(timeout=5)
    async def test_unchanged_tick_sends_nothing(self):
        fut, chunks = await self._open_and_wait('scopedkey')
        for _ in range(3):
            self._tick()
        self.dials[ALLOWED]['dial_name'] = 'Renamed'
        self._tick()
        await self._end(fut)

        events = self._events(chunks)
        assert len(events) == 2
        assert events[1] == ('dials', {'dials': [expected_item(ALLOWED, self.dials[ALLOWED])]})
        assert events[1][1]['dials'][0]['dial_name'] == 'Renamed'

    @tornado.testing.gen_test(timeout=5)
    async def test_burst_coalesces_to_one_event(self):
        fut, chunks = await self._open_and_wait('scopedkey')
        for value in (30, 40, 50):
            self.dials[ALLOWED]['value'] = value
        self._tick()
        await self._end(fut)

        events = self._events(chunks)
        assert len(events) == 2
        assert events[1][1]['dials'][0]['value'] == 50

    @tornado.testing.gen_test(timeout=5)
    async def test_delivery_states_are_streamed(self):
        fut, chunks = await self._open_and_wait('scopedkey')
        dial = self.dials[ALLOWED]
        steps = [
            ({'value_changed': True}, 'pending'),
            ({'value_fail_count': 2}, 'retrying'),
            ({'value_fail_count': 5, 'value_unresponsive': True}, 'unresponsive'),
            ({'value_changed': False, 'value_fail_count': 0, 'value_unresponsive': False}, 'delivered'),
        ]
        for count, (fields, state) in enumerate(steps, start=2):
            dial.update(fields)
            latest = await self._tick_and_wait(chunks, count)
            assert latest == ('dials', {'dials': [expected_item(ALLOWED, dial, value_delivery=state)]}), state
            assert latest[1]['dials'][0]['backlight_delivery'] == 'delivered'
        await self._end(fut)

    @tornado.testing.gen_test(timeout=5)
    async def test_image_revision_change_is_streamed(self):
        fut, chunks = await self._open_and_wait('scopedkey')
        self.fake_handler.image_revision[ALLOWED] = 1

        latest = await self._tick_and_wait(chunks, 2)
        assert latest == ('dials', {'dials': [expected_item(ALLOWED, self.dials[ALLOWED], image_rev=1)]})
        await self._end(fut)

    @tornado.testing.gen_test(timeout=5)
    async def test_access_revoked_mid_stream_drops_dial(self):
        fut, chunks = await self._open_and_wait('scopedkey')
        self.fake_config.keys['scopedkey'] = set()

        latest = await self._tick_and_wait(chunks, 2)
        assert latest == ('dials', {'dials': []})
        assert not fut.done()
        await self._end(fut)

    @tornado.testing.gen_test(timeout=5)
    async def test_access_granted_mid_stream_adds_dial(self):
        fut, chunks = await self._open_and_wait('scopedkey')
        self.fake_config.keys['scopedkey'] = {ALLOWED, DENIED}

        latest = await self._tick_and_wait(chunks, 2)
        assert [item['uid'] for item in latest[1]['dials']] == [ALLOWED, DENIED]
        await self._end(fut)

    @tornado.testing.gen_test(timeout=5)
    async def test_rescan_replaces_dial_set(self):
        fut, chunks = await self._open_and_wait('adminkey')
        self.fake_handler.dials = {'0123AB': make_dial('New')}

        latest = await self._tick_and_wait(chunks, 2)
        assert [item['uid'] for item in latest[1]['dials']] == ['0123AB']
        await self._end(fut)

    @tornado.testing.gen_test(timeout=5)
    async def test_deleted_key_sends_key_revoked_and_ends_stream(self):
        initial = expected_item(ALLOWED, self.dials[ALLOWED])
        fut, chunks = await self._open_and_wait('scopedkey')
        del self.fake_config.keys['scopedkey']
        self.dials[ALLOWED]['value'] = 99
        self._tick()

        response = await fut
        assert response.code == 200
        assert initial['value'] == 10
        assert self._events(chunks) == [('dials', {'dials': [initial]}), ('key_revoked', {})]
        assert not self.streams

        retry = await self.http_client.fetch(self.get_url(f'{EVENTS_PATH}?key=scopedkey'),
                                             raise_error=False, request_timeout=2)
        assert retry.code == 401

    @tornado.testing.gen_test(timeout=5)
    async def test_client_disconnect_unsubscribes(self):
        client = TCPClient()
        stream = await client.connect('127.0.0.1', self.get_http_port())
        try:
            await stream.write(f'GET {EVENTS_PATH}?key=scopedkey HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n'.encode('ascii'))
            head = await stream.read_until(b'\r\n\r\n')
            assert head.startswith(b'HTTP/1.1 200')

            await self._until(lambda: len(self.streams) == 1)
            handler = next(iter(self.streams))
        finally:
            stream.close()
            client.close()

        await self._until(lambda: not self.streams)
        assert handler.closed.is_set()
        # A finished handler raises on write(), so this fails unless push_dials checks `closed` first.
        self.dials[ALLOWED]['value'] = 77
        handler.push_dials()

    @tornado.testing.gen_test(timeout=5)
    async def test_http10_keepalive_client_sees_stream_end_after_key_revoked(self):
        client = TCPClient()
        stream = await client.connect('127.0.0.1', self.get_http_port())
        try:
            request = f'GET {EVENTS_PATH}?key=scopedkey HTTP/1.0\r\nConnection: keep-alive\r\n\r\n'
            await stream.write(request.encode('ascii'))
            head = await stream.read_until(b'\r\n\r\n')
            assert b'Transfer-Encoding' not in head and b'Content-Length' not in head

            await self._until(lambda: len(self.streams) == 1)
            del self.fake_config.keys['scopedkey']
            self._tick()
            body = await asyncio.wait_for(stream.read_until_close(), 2)
        finally:
            stream.close()
            client.close()

        assert [name for name, _data in parse_events(body)] == ['dials', 'key_revoked']
        assert not self.streams

    @tornado.testing.gen_test(timeout=5)
    async def test_http10_key_revoked_is_not_dropped_behind_a_pending_flush(self):
        client = TCPClient()
        stream = await client.connect('127.0.0.1', self.get_http_port())
        try:
            request = f'GET {EVENTS_PATH}?key=scopedkey HTTP/1.0\r\nConnection: keep-alive\r\n\r\n'
            await stream.write(request.encode('ascii'))
            await stream.read_until(b'\r\n\r\n')
            await stream.read_until(b'\n\n')
            server_stream = next(iter(self.streams)).request.connection.stream
            send = server_stream.write_to_fd
            sock = SimpleNamespace(sent=0, refused_at=None, full=False)

            def write_to_fd(data):
                if sock.full or sock.refused_at != sock.sent:
                    sock.refused_at = sock.sent
                    raise BlockingIOError
                end = bytes(data).index(b'\n\n') + 2
                sock.full = end < len(data)
                sent = send(data[:end])
                sock.sent += sent
                return sent

            # Server send-buffer stand-in: each event's first send is refused, and sending an event with another queued behind it fills the buffer for good.
            server_stream.write_to_fd = write_to_fd
            self.dials[ALLOWED]['value'] = 11
            self._tick()
            del self.fake_config.keys['scopedkey']
            self._tick()
            body = await asyncio.wait_for(stream.read_until_close(), 2)
        finally:
            stream.close()
            client.close()

        assert parse_events(body) == [('dials', {'dials': [expected_item(ALLOWED, self.dials[ALLOWED])]}), ('key_revoked', {})]


class PushDialsUnitTestCase(tornado.testing.AsyncTestCase):
    @staticmethod
    def _bare_stream(flush_future=None, key='scopedkey', dials=None):
        h = object.__new__(Dial_Get_Events)
        h.handler = FakeDialHandler(dials or {ALLOWED: make_dial('Allowed')})
        h.config = FakeConfig()
        h.streams = {h}
        h.closed = asyncio.Event()
        h.last_data = None
        h.last_write = 0.0
        h.pending_flush = None
        h.written = []
        h.get_argument = lambda name, default=None: key
        h.write = h.written.append

        def flush():
            if flush_future is not None:
                return flush_future
            resolved = Future()
            resolved.set_result(None)
            return resolved

        h.flush = flush
        return h

    def test_push_is_skipped_while_a_flush_is_pending(self):
        pending = Future()
        h = self._bare_stream(flush_future=pending)

        h.push_dials()
        assert len(h.written) == 1
        sent = h.last_data

        h.handler.dials[ALLOWED]['value'] = 77
        h.push_dials()
        assert len(h.written) == 1
        assert h.last_data == sent

        pending.set_result(None)
        h.push_dials()
        assert len(h.written) == 2
        assert parse_events(h.written[1].encode('utf-8')) == [
            ('dials', {'dials': [expected_item(ALLOWED, make_dial('Allowed', value=77))]})]

    def test_revocation_ends_stream_while_a_flush_is_pending(self):
        h = self._bare_stream(flush_future=Future())

        h.push_dials()
        del h.config.keys['scopedkey']
        h.push_dials()
        assert h.written[-1] == 'event: key_revoked\ndata: {}\n\n'
        assert h.closed.is_set()
        assert not h.streams

    def test_keepalive_after_quiet_interval(self):
        assert Dial_Get_Events.KEEPALIVE_SECONDS == 15
        h = self._bare_stream()
        clock = SimpleNamespace(now=100.0)

        # Only the monotonic clock is faked, so reading the wall clock instead shows.
        with mock.patch.object(server.time, 'monotonic', lambda: clock.now):
            h.push_dials()
            clock.now = 114.9
            h.push_dials()
            assert len(h.written) == 1

            clock.now = 115.0
            h.push_dials()
            assert h.written[1:] == [': keepalive\n\n']

            clock.now = 129.9
            h.push_dials()
            assert len(h.written) == 2

    def test_failed_flush_ends_stream(self):
        failed = Future()
        failed.set_exception(OSError())
        h = self._bare_stream(flush_future=failed)

        h.push_dials()
        assert h.closed.is_set()
        assert not h.streams


def test_public_dial_state_is_the_list_item_and_copies_backlight():
    dial = make_dial('CPU', value=60, backlight={'red': 0, 'green': 50, 'blue': 100, 'white': 7})

    state = public_dial_state(ALLOWED, dial)
    assert state == {
        'uid': ALLOWED,
        'dial_name': 'CPU',
        'value': 60,
        'backlight': {'red': 0, 'green': 50, 'blue': 100},
        'image_file': '/srv/upload/img_CPU',
    }
    assert list(state) == LIST_ITEM_KEYS

    state['backlight']['red'] = 255
    assert dial['backlight'] == {'red': 0, 'green': 50, 'blue': 100, 'white': 7}


@pytest.mark.parametrize('kind', ['value', 'backlight'])
@pytest.mark.parametrize('changed,fail_count,unresponsive,state', [
    (False, 0, False, 'delivered'),
    (True, 0, False, 'pending'),
    (True, 2, False, 'retrying'),
    (True, 5, True, 'unresponsive'),
    (False, 0, True, 'unresponsive'),
    (False, 2, False, 'delivered'),
])
def test_dial_delivery_state(kind, changed, fail_count, unresponsive, state):
    other = 'backlight' if kind == 'value' else 'value'
    # The other kind's flags always imply a different state, so a mixed-up kind shows.
    other_flags = (False, 0, False) if state == 'unresponsive' else (True, 5, True)
    dial = make_dial('Any', **{
        f'{kind}_changed': changed, f'{kind}_fail_count': fail_count, f'{kind}_unresponsive': unresponsive,
        f'{other}_changed': other_flags[0], f'{other}_fail_count': other_flags[1],
        f'{other}_unresponsive': other_flags[2],
    })

    assert dial_delivery_state(dial, kind) == state


def test_dial_delivery_state_defaults_to_delivered_for_missing_keys():
    assert dial_delivery_state({}, 'value') == 'delivered'


def test_push_dial_events_drops_a_failing_stream_and_serves_the_rest():
    calls = []

    def explode():
        raise ZeroDivisionError

    bad = SimpleNamespace(push_dials=explode, end_stream=lambda: calls.append(('bad', 'end_stream')))
    good = SimpleNamespace(push_dials=lambda: calls.append(('good', 'push_dials')),
                           end_stream=lambda: calls.append(('good', 'end_stream')))

    push_dial_events([bad, good])
    assert calls == [('bad', 'end_stream'), ('good', 'push_dials')]


def _periodic_service(job, calls, threads):
    def push():
        calls.append('push')
        threads['push'] = threading.get_ident()

    service = object.__new__(server.Dial_API_Service)
    service.serial_executor = ThreadPoolExecutor(max_workers=1)
    service.dial_handler = SimpleNamespace(periodic_dial_update=job)
    service.dial_event_streams = [SimpleNamespace(push_dials=push, end_stream=lambda: calls.append('end'))]
    return service


def test_periodic_update_pushes_on_ioloop_thread_after_serial_job():
    calls = []
    threads = {}

    def job():
        calls.append('job')
        threads['job'] = threading.get_ident()

    service = _periodic_service(job, calls, threads)
    try:
        asyncio.run(service.periodic_dial_update())
    finally:
        service.serial_executor.shutdown(wait=True)

    main = threading.get_ident()
    assert calls == ['job', 'push']
    assert threads['job'] != main
    assert threads['push'] == main


def test_periodic_update_pushes_when_serial_job_raises():
    calls = []

    def job():
        raise OSError('hub unplugged')

    service = _periodic_service(job, calls, {})
    try:
        with pytest.raises(OSError):
            asyncio.run(service.periodic_dial_update())
    finally:
        service.serial_executor.shutdown(wait=True)

    assert calls == ['push']


def test_run_forever_schedules_the_pushing_tick(monkeypatch):
    scheduled = []
    service = object.__new__(server.Dial_API_Service)
    service.handlers = []
    service.server_settings = {}
    service.config = SimpleNamespace(get_server_config=lambda: {'master_key': 'k', 'dial_update_period': 200})
    monkeypatch.setattr(server, 'Application', lambda *a, **k: SimpleNamespace(listen=lambda *a, **k: None))
    monkeypatch.setattr(server.IOLoop, 'instance', staticmethod(lambda: SimpleNamespace(start=lambda: None)))
    monkeypatch.setattr(server, 'PeriodicCallback',
                        lambda callback, period: scheduled.append((callback, period)) or SimpleNamespace(start=lambda: None))

    service.run_forever()
    assert scheduled == [(service.periodic_dial_update, 200)]


def test_dial_set_image_bumps_image_revision():
    handler = object.__new__(ServerDialHandler)
    handler.dials = {ALLOWED: make_dial('Allowed')}
    handler.image_revision = {}

    assert handler.dial_set_image(ALLOWED, '/srv/upload/img_one') is True
    assert handler.dial_set_image(ALLOWED, '/srv/upload/img_two') is True
    assert handler.image_revision == {ALLOWED: 2}

    assert handler.dial_set_image(DENIED, '/srv/upload/img_three') is False
    assert handler.image_revision == {ALLOWED: 2}


def test_server_dial_handler_starts_with_empty_image_revision():
    handler = ServerDialHandler(
        SimpleNamespace(get_dial_list=lambda rescan: [], set_all_dials_to=lambda value: None),
        SimpleNamespace(get_server_config=lambda: {}),
    )

    assert isinstance(handler.image_revision, dict)
    assert not handler.image_revision
    assert 'image_revision' not in vars(ServerDialHandler)
