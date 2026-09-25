"""Blocking serial I/O runs on the single-worker executor; records and the database stay on the IOLoop thread."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import tornado.testing
import tornado.web

from database import DialsDB
from server import (
    Device_SetRaw_Handler,
    Dial_Set_Calibration,
    Dial_Reload_Device_Info,
    Dial_Provision,
    Dial_Set_Easing,
)


def test_database_rejects_use_from_another_thread(tmp_path):
    db = DialsDB(database_file=str(tmp_path / "threaded.db"))

    with ThreadPoolExecutor(max_workers=1) as ex:
        with pytest.raises(Exception, match="same thread"):
            ex.submit(db.api_key_generate, 'worker', 1).result()


class FakeDialHandler:
    """Records each call with whether it ran on the IOLoop (test) thread."""

    def __init__(self, ioloop_thread):
        self.ioloop_thread = ioloop_thread
        self.calls = []

    def _record(self, *call):
        self.calls.append((*call, threading.current_thread() is self.ioloop_thread))

    def dial_set_raw(self, dial_uid, value):
        self._record('dial_set_raw', dial_uid, value)
        return True

    def dial_set_calibration(self, dial_uid, value, fullScale=False):
        self._record('dial_set_calibration', dial_uid, value)
        return True

    def dial_read_info_from_hardware(self, gaugeUID):
        self._record('dial_read_info_from_hardware', gaugeUID)
        return {'fw_version': '1.0'}

    def dial_store_info(self, gaugeUID, info):
        self._record('dial_store_info', gaugeUID)
        return {'uid': gaugeUID, **info}

    def provision_dials(self):
        self._record('provision_dials')
        return {0: 'ABCDEF'}

    def rebuild_dials(self, scan):
        self._record('rebuild_dials', scan)
        return {uid: {'uid': uid} for uid in scan.values()}

    def dial_send_easing(self, dial_uid, target, step=None, period=None):
        self._record('dial_send_easing', dial_uid)
        return {f'{target}_step': step}

    def dial_store_easing(self, dial_uid, sent):
        self._record('dial_store_easing', dial_uid, sent)


class FakeConfig:
    def is_valid_api_key(self, key):
        return key == 'testkey'

    def validate_admin_key(self, key):
        return key == 'adminkey'

    def api_key_has_access_to_dial(self, api_key, gaugeUID):
        return True


class AsyncHandlerOffloadTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.fake_handler = FakeDialHandler(threading.current_thread())
        # A real single-worker executor, exactly as production wires it.
        self.executor = ThreadPoolExecutor(max_workers=1)
        hc = {
            "handler": self.fake_handler,
            "config": FakeConfig(),
            "executor": self.executor,
        }
        return tornado.web.Application([
            (r"/api/v0/dial/provision", Dial_Provision, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/setRaw", Device_SetRaw_Handler, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/calibrate", Dial_Set_Calibration, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/reload", Dial_Reload_Device_Info, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/easing/(dial|backlight)", Dial_Set_Easing, hc),
        ])

    def tearDown(self):
        super().tearDown()
        self.executor.shutdown(wait=True)

    def test_setraw_runs_through_executor_and_returns_201(self):
        response = self.fetch("/api/v0/dial/ABCDEF/setRaw?key=testkey&value=7")
        assert response.code == 201
        assert self.fake_handler.calls == [('dial_set_raw', 'ABCDEF', '7', False)]

    def test_calibrate_runs_through_executor_and_returns_201(self):
        response = self.fetch("/api/v0/dial/ABCDEF/calibrate?key=testkey&value=9")
        assert response.code == 201
        assert self.fake_handler.calls == [('dial_set_calibration', 'ABCDEF', '9', False)]

    def test_reload_reads_on_executor_and_stores_on_ioloop(self):
        response = self.fetch("/api/v0/dial/ABCDEF/reload?key=testkey")
        body = json.loads(response.body)
        assert response.code == 200
        assert body['data'] == {'uid': 'ABCDEF', 'fw_version': '1.0'}
        assert self.fake_handler.calls == [
            ('dial_read_info_from_hardware', 'ABCDEF', False),
            ('dial_store_info', 'ABCDEF', True),
        ]

    def test_provision_scans_on_executor_and_rebuilds_on_ioloop(self):
        response = self.fetch("/api/v0/dial/provision?admin_key=adminkey")
        assert json.loads(response.body)['data'] == {'ABCDEF': {'uid': 'ABCDEF'}}
        assert self.fake_handler.calls == [
            ('provision_dials', False),
            ('rebuild_dials', {0: 'ABCDEF'}, True),
        ]

    def test_easing_sends_on_executor_and_stores_on_ioloop(self):
        response = self.fetch("/api/v0/dial/ABCDEF/easing/dial?key=testkey&step=4")
        assert response.code == 200
        assert self.fake_handler.calls == [
            ('dial_send_easing', 'ABCDEF', False),
            ('dial_store_easing', 'ABCDEF', {'dial_step': 4}, True),
        ]
