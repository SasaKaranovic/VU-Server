"""Bug #3: blocking serial I/O must run off the Tornado IOLoop thread.

The periodic dial updater and the handlers that do blocking serial round-trips
(setRaw, calibrate, easing, reload, provision, reset_all) previously ran
synchronously on the single IOLoop thread, freezing every other request and the
periodic updater for the duration of the (up to multi-second) serial exchange.

These are now offloaded to a dedicated single-worker executor. That means:
  * the SQLite connection is touched from a worker thread, so it must be
    thread-safe (check_same_thread=False + serialized access); and
  * the affected handlers become coroutines that still return correct
    responses and still enforce per-dial access control.
"""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import tornado.testing
import tornado.web

from database import DialsDB
from server import (
    Device_SetRaw_Handler,
    Dial_Set_Calibration,
    Dial_Reload_Device_Info,
)


# -- DB must survive being used from the executor thread ----------------------

def test_database_is_usable_from_a_worker_thread(tmp_path):
    db = DialsDB(database_file=str(tmp_path / "threaded.db"), init_if_missing=True)

    # Simulate the serial executor doing a DB write on its own thread (e.g.
    # provision/reload persisting dial info). With a default sqlite connection
    # this raises "SQLite objects created in a thread can only be used in that
    # same thread".
    with ThreadPoolExecutor(max_workers=1) as ex:
        key = ex.submit(db.api_key_generate, 'worker', 1).result()

    assert key
    assert key in db.api_key_list()


# -- Offloaded handlers still behave correctly --------------------------------

class FakeDialHandler:
    def __init__(self):
        self.calls = []

    def dial_set_raw(self, dial_uid, value):
        self.calls.append(('dial_set_raw', dial_uid, value))
        return True

    def dial_set_calibration(self, dial_uid, value, fullScale=False):
        self.calls.append(('dial_set_calibration', dial_uid, value))
        return True

    def dial_reload_info_from_hardware(self, gaugeUID):
        self.calls.append(('dial_reload_info_from_hardware', gaugeUID))
        return {'uid': gaugeUID, 'fw_version': '1.0'}


class FakeConfig:
    def is_valid_api_key(self, key):
        return key == 'testkey'

    def api_key_has_access_to_dial(self, api_key, gaugeUID):
        return True


class AsyncHandlerOffloadTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.fake_handler = FakeDialHandler()
        # A real single-worker executor, exactly as production wires it.
        self.executor = ThreadPoolExecutor(max_workers=1)
        hc = {
            "handler": self.fake_handler,
            "config": FakeConfig(),
            "executor": self.executor,
        }
        return tornado.web.Application([
            (r"/api/v0/dial/([0-9A-F]*?)/setRaw", Device_SetRaw_Handler, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/calibrate", Dial_Set_Calibration, hc),
            (r"/api/v0/dial/([0-9A-F]*?)/reload", Dial_Reload_Device_Info, hc),
        ])

    def test_setraw_runs_through_executor_and_returns_201(self):
        response = self.fetch("/api/v0/dial/ABCDEF/setRaw?key=testkey&value=7")
        assert response.code == 201
        assert ('dial_set_raw', 'ABCDEF', '7') in self.fake_handler.calls

    def test_calibrate_runs_through_executor_and_returns_201(self):
        response = self.fetch("/api/v0/dial/ABCDEF/calibrate?key=testkey&value=9")
        assert response.code == 201
        assert ('dial_set_calibration', 'ABCDEF', '9') in self.fake_handler.calls

    def test_reload_runs_through_executor_and_returns_data(self):
        response = self.fetch("/api/v0/dial/ABCDEF/reload?key=testkey")
        body = json.loads(response.body)
        assert response.code == 200
        assert body['data'] == {'uid': 'ABCDEF', 'fw_version': '1.0'}
        assert ('dial_reload_info_from_hardware', 'ABCDEF') in self.fake_handler.calls
