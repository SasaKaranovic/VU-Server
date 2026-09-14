import json

import tornado.testing
import tornado.web

from server import Dial_Get_List


class FakeDialHandler:
    def __init__(self, dials):
        self.dials = dials

    def get_dial_info(self, dial_uid=None):
        if dial_uid is not None:
            return self.dials.get(dial_uid, None)
        return self.dials


class FakeConfig:
    def is_valid_api_key(self, key):
        return key == 'testkey'

    def api_key_has_access_to_dial(self, api_key, gaugeUID):
        return True


class DialGetListTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.dials = {
            'ABC123': {
                'dial_name': 'Test Dial',
                'value': 42,
                'backlight': {'red': 1, 'green': 2, 'blue': 3, 'white': 4},
                'image_file': 'img_blank',
            }
        }
        self.fake_handler = FakeDialHandler(self.dials)
        self.fake_config = FakeConfig()
        handlers_config = {"handler": self.fake_handler, "config": self.fake_config}
        return tornado.web.Application([
            (r"/api/v0/dial/list", Dial_Get_List, handlers_config),
        ])

    def test_does_not_mutate_stored_backlight_state(self):
        response = self.fetch("/api/v0/dial/list?key=testkey")
        body = json.loads(response.body)

        assert response.code == 200
        assert 'white' not in body['data'][0]['backlight']

        # The handler must not have popped 'white' from the live dial state
        assert self.dials['ABC123']['backlight'] == {'red': 1, 'green': 2, 'blue': 3, 'white': 4}

    def test_second_request_still_succeeds(self):
        self.fetch("/api/v0/dial/list?key=testkey")
        response = self.fetch("/api/v0/dial/list?key=testkey")
        body = json.loads(response.body)

        assert response.code == 200
        assert body['data'][0]['backlight'] == {'red': 1, 'green': 2, 'blue': 3}
