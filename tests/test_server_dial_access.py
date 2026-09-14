"""Regression tests for per-dial API-key authorization.

Bug #16: every per-dial control/read endpoint only checked that the API key
*existed* (`is_valid_api_key`) and skipped `api_key_has_access_to_dial`. A key
scoped to dial A could therefore command or read dial B by putting B's UID in
the URL. The `dial_access` grant was only ever enforced by the list endpoint.

`ALLOWED` is a UID the scoped key may touch; `DENIED` is one it may not. Both
are hex strings because the route regex only accepts `[0-9A-F]`.
"""
import json

import tornado.testing
import tornado.web

from server import (
    Device_Status_Handler,
    Device_Set_Handler,
    Device_SetRaw_Handler,
    Device_Backlight_Handler,
    Device_Set_Image,
    Dial_Get_Image,
    Dial_Get_Image_CRC,
    Dial_Set_Dial_Name,
    Dial_Reload_Device_Info,
    Dial_Reset_Device,
    Dial_Set_Calibration,
    Dial_Set_Easing_Dial,
    Dial_Set_Easing_Backlight,
)

ALLOWED = 'ABCDEF'
DENIED = 'FED210'


class FakeDialHandler:
    def __init__(self):
        self.calls = []

    def _record(self, name):
        self.calls.append(name)

    def get_dial_info(self, dial_uid=None):
        self._record('get_dial_info')
        return {'uid': dial_uid, 'value': 0}

    def dial_set_percent(self, dial_uid, value):
        self._record('dial_set_percent')
        return True

    def dial_set_raw(self, dial_uid, value):
        self._record('dial_set_raw')
        return True

    def dial_set_backlight(self, dial_uid, red, green, blue, white):
        self._record('dial_set_backlight')
        return True

    def dial_set_image(self, dial_uid, image_file):
        self._record('dial_set_image')
        return True

    def reset_device(self, gaugeUID):
        self._record('reset_device')
        return True

    def dial_reload_info_from_hardware(self, gaugeUID):
        self._record('dial_reload_info_from_hardware')
        return {'uid': gaugeUID}

    def dial_set_calibration(self, dial_uid, value, fullScale=False):
        self._record('dial_set_calibration')
        return True

    def dial_set_easing_dial(self, dial_uid, step=None, period=None):
        self._record('dial_set_easing_dial')
        return True

    def dial_set_easing_backlight(self, dial_uid, step=None, period=None):
        self._record('dial_set_easing_backlight')
        return True

    def dial_reload_info_from_database(self, gaugeUID):
        self._record('dial_reload_info_from_database')
        return True


class FakeConfig:
    def is_valid_api_key(self, key):
        return key in ('scopedkey', 'adminkey')

    def api_key_has_access_to_dial(self, api_key, gaugeUID):
        if api_key == 'adminkey':
            return True
        if api_key == 'scopedkey':
            return gaugeUID == ALLOWED
        return False

    def update_dial_db_cell(self, dial_uid, cell, value):
        return True

    def update_dial_db_cell_with_dict(self, dial_uid, values_dict):
        return True


# Each entry: (name, method, url_template, extra_query). {uid} is substituted.
ENDPOINTS = [
    ('status', 'GET', "/api/v0/dial/{uid}/status", ''),
    ('set', 'GET', "/api/v0/dial/{uid}/set", '&value=50'),
    ('setRaw', 'GET', "/api/v0/dial/{uid}/setRaw", '&value=50'),
    ('backlight', 'GET', "/api/v0/dial/{uid}/backlight", '&red=1'),
    ('image_get', 'GET', "/api/v0/dial/{uid}/image/get", ''),
    ('image_crc', 'GET', "/api/v0/dial/{uid}/image/crc", ''),
    ('name', 'GET', "/api/v0/dial/{uid}/name", '&name=hello'),
    ('reload', 'GET', "/api/v0/dial/{uid}/reload", ''),
    ('reset', 'GET', "/api/v0/dial/{uid}/reset", ''),
    ('calibrate', 'GET', "/api/v0/dial/{uid}/calibrate", '&value=1'),
    ('easing_dial', 'GET', "/api/v0/dial/{uid}/easing/dial", '&step=1'),
    ('easing_backlight', 'GET', "/api/v0/dial/{uid}/easing/backlight", '&step=1'),
    ('image_set', 'POST', "/api/v0/dial/{uid}/image/set", ''),
]


class DialAccessControlTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.fake_handler = FakeDialHandler()
        self.fake_config = FakeConfig()
        hc = {"handler": self.fake_handler, "config": self.fake_config}
        return tornado.web.Application([
            (r"/api/v0/dial/([0-9A-F]*?)/status", Device_Status_Handler, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/set", Device_Set_Handler, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/setRaw", Device_SetRaw_Handler, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/image/set", Device_Set_Image, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/image/get", Dial_Get_Image, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/image/crc", Dial_Get_Image_CRC, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/backlight", Device_Backlight_Handler, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/name", Dial_Set_Dial_Name, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/reload", Dial_Reload_Device_Info, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/reset", Dial_Reset_Device, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/calibrate", Dial_Set_Calibration, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/easing/dial", Dial_Set_Easing_Dial, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/easing/backlight", Dial_Set_Easing_Backlight, hc),
        ])

    def _fetch(self, method, url):
        if method == 'POST':
            return self.fetch(url, method='POST', body=b'')
        return self.fetch(url)

    def test_scoped_key_is_denied_on_every_dial_endpoint(self):
        for name, method, tmpl, extra in ENDPOINTS:
            self.fake_handler.calls.clear()
            url = tmpl.format(uid=DENIED) + f"?key=scopedkey{extra}"
            response = self._fetch(method, url)

            assert response.code == 403, (
                f"{name}: expected 403 for a key without access to the dial, "
                f"got {response.code}")
            body = json.loads(response.body)
            assert body['status'] == 'fail', f"{name}: {body}"
            # The privileged action must never have been executed.
            assert self.fake_handler.calls == [], (
                f"{name}: handler action(s) {self.fake_handler.calls} ran "
                "despite the key lacking access to the dial")

    def test_scoped_key_is_allowed_on_its_own_dial(self):
        response = self.fetch(f"/api/v0/dial/{ALLOWED}/set?key=scopedkey&value=50")
        assert response.code == 200
        assert 'dial_set_percent' in self.fake_handler.calls

    def test_admin_key_has_wildcard_access(self):
        response = self.fetch(f"/api/v0/dial/{DENIED}/set?key=adminkey&value=50")
        assert response.code == 200
        assert 'dial_set_percent' in self.fake_handler.calls
