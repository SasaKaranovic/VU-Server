"""Raw-set and calibration failures must reach the API caller.

`dial_set_raw` / `dial_set_calibration` returned True whatever the hub replied,
and `/calibrate` ignored the result, so a NAK or unknown dial still got 201.
"""
import json
import types

import tornado.testing
import tornado.web

from server import Dial_Set_Calibration
from server_dial_handler import ServerDialHandler


def _handler_with_nak_driver():
    handler = object.__new__(ServerDialHandler)
    handler.dials = {'AAA': {'uid': 'AAA', 'index': 0}}
    handler.dial_driver = types.SimpleNamespace(
        dial_single_set_raw=lambda index, value: False,
        dial_calibrate=lambda index, value, fullScale: False,
    )
    return handler


def test_dial_set_raw_returns_driver_failure():
    assert _handler_with_nak_driver().dial_set_raw('AAA', 100) is False


def test_dial_set_calibration_returns_driver_failure():
    assert _handler_with_nak_driver().dial_set_calibration('AAA', 100) is False


class FakeDialHandler:
    def dial_set_calibration(self, dial_uid, value, fullScale=False):
        return False


class FakeConfig:
    def is_valid_api_key(self, key):
        return key == 'testkey'

    def api_key_has_access_to_dial(self, api_key, gaugeUID):
        return True


class CalibrateFailureTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        handlers_config = {"handler": FakeDialHandler(), "config": FakeConfig()}
        return tornado.web.Application([
            (r"/api/v0/dial/([0-9A-F]*?)/calibrate", Dial_Set_Calibration, handlers_config),
        ])

    def test_failed_calibration_is_reported(self):
        response = self.fetch("/api/v0/dial/ABC123/calibrate?key=testkey&value=100")
        body = json.loads(response.body)

        assert response.code == 503
        assert body['status'] == 'fail'
