import json

import tornado.testing
import tornado.web

from server import Admin_Keys_Update


class FakeConfig:
    def __init__(self):
        self.updated_names = []
        self.dial_access_calls = []

    def validate_admin_key(self, key):
        return key == 'adminkey'

    def is_valid_api_key(self, key):
        return key == 'userkey'

    def update_api_key(self, key_uid, key_name):
        self.updated_names.append((key_uid, key_name))
        return True

    def api_key_add_dial_access(self, key, dials):
        self.dial_access_calls.append((key, dials))
        return True


class KeysUpdateTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.fake_config = FakeConfig()
        handlers_config = {"handler": None, "config": self.fake_config}
        return tornado.web.Application([
            (r"/api/v0/admin/keys/update", Admin_Keys_Update, handlers_config),
        ])

    def _post(self, body):
        return self.fetch("/api/v0/admin/keys/update", method="POST", body=body)

    def test_name_only_update_reports_success(self):
        # A rename with no `dials` argument must succeed. The old handler only
        # ever returned 'ok' from inside the dial-access branch, so a name-only
        # update always fell through to 'Failed to update key!'.
        response = self._post("admin_key=adminkey&key=userkey&name=NewName")
        body = json.loads(response.body)

        assert response.code == 200
        assert body['status'] == 'ok'
        assert self.fake_config.updated_names == [('userkey', 'NewName')]

    def test_dial_access_only_update_reports_success(self):
        response = self._post("admin_key=adminkey&key=userkey&dials=AAA;BBB")
        body = json.loads(response.body)

        assert response.code == 200
        assert body['status'] == 'ok'
        assert self.fake_config.dial_access_calls == [('userkey', ['AAA', 'BBB'])]

    def test_name_and_dials_update_reports_success(self):
        response = self._post("admin_key=adminkey&key=userkey&name=NewName&dials=AAA")
        body = json.loads(response.body)

        assert response.code == 200
        assert body['status'] == 'ok'
        assert self.fake_config.updated_names == [('userkey', 'NewName')]
        assert self.fake_config.dial_access_calls == [('userkey', ['AAA'])]
