"""The easing endpoints for the needle and the backlight share one handler."""
import json

import tornado.testing
import tornado.web

import server


class FakeDialHandler:
    def __init__(self):
        self.easing_calls = []
        self.stored = []
        self.present = True

    def dial_send_easing(self, dial_uid, target, step=None, period=None):
        self.easing_calls.append((dial_uid, target, step, period))
        return {f'{target}_step': step} if self.present else None

    def dial_store_easing(self, dial_uid, sent):
        self.stored.append((dial_uid, sent))


class FakeConfig:
    def is_valid_api_key(self, key):
        return key == 'testkey'

    def api_key_has_access_to_dial(self, api_key, gaugeUID):
        return True


class EasingTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.fake_handler = FakeDialHandler()
        handlers_config = {"handler": self.fake_handler, "config": FakeConfig()}
        return tornado.web.Application(server.make_routes(handlers_config))

    def _get(self, path):
        response = self.fetch(f"/api/v0/dial/ABC123/{path}")
        return response, json.loads(response.body)

    def test_step_only(self):
        response, body = self._get("easing/dial?key=testkey&step=5")
        assert response.code == 200
        assert body['status'] == 'ok'
        assert self.fake_handler.easing_calls == [('ABC123', 'dial', 5, None)]
        assert self.fake_handler.stored == [('ABC123', {'dial_step': 5})]

    def test_period_only(self):
        response, _ = self._get("easing/dial?key=testkey&period=250")
        assert response.code == 200
        assert self.fake_handler.easing_calls == [('ABC123', 'dial', None, 250)]

    def test_backlight_path_targets_backlight(self):
        response, _ = self._get("easing/backlight?key=testkey&step=5&period=250")
        assert response.code == 200
        assert self.fake_handler.easing_calls == [('ABC123', 'backlight', 5, 250)]

    def test_missing_step_and_period_is_400(self):
        response, _ = self._get("easing/dial?key=testkey")
        assert response.code == 400
        assert self.fake_handler.easing_calls == []

    def test_non_numeric_step_is_400(self):
        response, body = self._get("easing/dial?key=testkey&step=abc")
        assert response.code == 400
        assert body['status'] == 'fail'
        assert self.fake_handler.easing_calls == []

    def test_unknown_dial_is_406(self):
        self.fake_handler.present = False
        response, _ = self._get("easing/backlight?key=testkey&step=5")
        assert response.code == 406
        assert self.fake_handler.stored == []

    def test_unknown_easing_target_is_json_404(self):
        response, body = self._get("easing/get?key=testkey")
        assert response.code == 404
        assert body['status'] == 'fail'
