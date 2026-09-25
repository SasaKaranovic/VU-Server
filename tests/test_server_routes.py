"""Routing, /status response shape and query-flag parsing for the assembled application."""
import json

import pytest
import tornado.testing
import tornado.web

import server


DIAL = {
    'uid': 'ABC123', 'index': '0', 'dial_name': 'Test Dial', 'value': 42,
    'backlight': {'red': 1, 'green': 2, 'blue': 3, 'white': 4},
    'image_file': '/upload/img_blank',
    'easing': {'dial_step': 5, 'dial_period': 50, 'backlight_step': 5, 'backlight_period': 50},
    'fw_hash': 'abc', 'fw_version': '1.0', 'hw_version': '2', 'protocol_version': '1',
    'value_changed': False, 'backlight_changed': True, 'image_changed': False,
    'value_fail_count': 0, 'value_retry_after': 0, 'value_unresponsive': False,
    'backlight_fail_count': 3, 'backlight_retry_after': 12.5, 'backlight_unresponsive': False,
}


class FakeDialHandler:
    def get_dial_info(self, dial_uid=None):
        return DIAL if dial_uid == DIAL['uid'] else None


class FakeConfig:
    def is_valid_api_key(self, key):
        return key == 'testkey'

    def api_key_has_access_to_dial(self, api_key, gaugeUID):
        return True


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True), (True, True),
    ("false", False), ("0", False), ("", False), ("no", False), (False, False),
])
def test_arg_is_true_parses_query_string_values(value, expected):
    # get_argument returns a string when the flag is present, never the True singleton.
    assert server.BaseHandler._arg_is_true(value) is expected


class RoutesTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        hc = {"handler": FakeDialHandler(), "config": FakeConfig()}
        return tornado.web.Application(server.make_routes(hc))

    def test_status_returns_public_fields_only(self):
        response = self.fetch("/api/v0/dial/ABC123/status?key=testkey")
        body = json.loads(response.body)

        assert response.code == 200
        assert body['data'] == {field: DIAL[field] for field in server.STATUS_FIELDS}
        assert not any(k.endswith(('_fail_count', '_retry_after', '_unresponsive'))
                       for k in body['data'])

    def test_root_serves_index_html(self):
        response = self.fetch("/")
        assert response.code == 200
        assert response.headers['Content-Type'].startswith('text/html')
        with open(f"{server.WEB_ROOT}/index.html", 'rb') as fh:
            assert response.body == fh.read()

    def test_unknown_api_path_is_json_404(self):
        response = self.fetch("/api/v0/nope")
        assert response.code == 404
        assert json.loads(response.body)['status'] == 'fail'

    def test_unknown_static_path_is_404(self):
        assert self.fetch("/missing.html").code == 404


@pytest.mark.parametrize('value', ['', 'DEBUG', 'warning'])
def test_logging_flag_accepts_any_level(value):
    """The add-on passes '' when its option lookup fails; that must start at info, not exit."""
    assert server.parse_args(['--logging', value]).logging == value
