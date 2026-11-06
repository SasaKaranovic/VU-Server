"""Unknown `/api/*` paths must get the JSON 404 from Default_404_Handler.

The `/(.*)` StaticFileHandler catch-all matches every path, so Tornado never
falls back to `default_handler_class` and API clients got a text/plain 404.
"""
import json
import types

import pytest
import tornado.testing
import tornado.web

import server


def _build_service():
    # Construct the real route table with hardware and config stubbed out.
    fake_config = types.SimpleNamespace(get_hardware_config=lambda: {'port': 'COM_TEST'},
                                        is_valid_api_key=lambda _key: False)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(server, 'pid_lock', lambda *a, **k: None)
        mp.setattr(server.signal, 'signal', lambda *a, **k: None)
        mp.setattr(server, 'ServerConfig', lambda _path: fake_config)
        mp.setattr(server, 'DialSerialDriver', lambda _port: None)
        mp.setattr(server, 'ServerDialHandler',
                   lambda _driver, _config: types.SimpleNamespace(dials={'AAA': {}}))
        service = server.Dial_API_Service()
    service.serial_executor.shutdown(wait=False)
    return service


class UnknownApiPathTestCase(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        service = _build_service()
        return tornado.web.Application(service.handlers, **service.server_settings)

    def test_unknown_api_path_returns_json_404(self):
        response = self.fetch('/api/v0/does/not/exist')

        assert response.code == 404
        assert response.headers['Content-Type'].startswith('application/json')
        assert json.loads(response.body)['status'] == 'fail'

    def test_dial_events_route_is_ahead_of_api_catch_all(self):
        response = self.fetch('/api/v0/dial/events?key=x')

        assert response.code == 401
        assert response.headers['Content-Type'].startswith('application/json')
        assert json.loads(response.body)['message'] == 'Unauthorized'


def test_dial_events_route_gets_the_stream_set_the_tick_pushes_to():
    service = _build_service()

    [kwargs] = [route[2] for route in service.handlers if route[0] == r"/api/v0/dial/events"]
    assert kwargs['streams'] is service.dial_event_streams
