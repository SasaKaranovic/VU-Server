"""`server.hostname` from config.yaml must control the listen address.

`run_forever` read the port from config but called `app.listen(port)` with no
address, so Tornado bound every interface (0.0.0.0) regardless of the
`hostname: localhost` entry -- while the log line claimed `localhost`. With
`Access-Control-Allow-Origin: *` and a well-known default master key, that
exposed dial administration to the whole LAN out of the box.
"""
import types

import server


class _FakeApp:
    """Records what Application.listen() is asked to bind."""
    listen_calls = []

    def __init__(self, *args, **kwargs):
        pass

    def listen(self, port, address=None, **kwargs):
        _FakeApp.listen_calls.append((port, address))


class _FakeLoop:
    def start(self):
        pass

    def run_in_executor(self, *args, **kwargs):  # pragma: no cover - unused
        raise AssertionError("periodic update must not run in this test")


def _service(server_cfg):
    service = object.__new__(server.Dial_API_Service)
    service.handlers = []
    service.server_settings = {}
    service.serial_executor = None
    service.dial_handler = types.SimpleNamespace(periodic_dial_update=lambda: None)
    service.config = types.SimpleNamespace(get_server_config=lambda: server_cfg)
    return service


def _run(monkeypatch, server_cfg):
    _FakeApp.listen_calls = []
    monkeypatch.setattr(server, 'Application', _FakeApp)
    monkeypatch.setattr(server.IOLoop, 'instance', staticmethod(lambda: _FakeLoop()))
    monkeypatch.setattr(server, 'PeriodicCallback',
                        lambda cb, period: types.SimpleNamespace(start=lambda: None))
    _service(server_cfg).run_forever()
    return _FakeApp.listen_calls


def test_run_forever_binds_to_configured_hostname(monkeypatch):
    calls = _run(monkeypatch, {
        'hostname': '127.0.0.1', 'port': 5340, 'master_key': 'k', 'dial_update_period': 200,
    })
    assert calls == [(5340, '127.0.0.1')], (
        f"expected listen(5340, address='127.0.0.1'); got {calls}")


def test_run_forever_binds_all_interfaces_when_hostname_is_empty(monkeypatch):
    # An explicitly blank hostname is the documented way to opt in to LAN
    # access; Tornado treats ''/None as "all interfaces".
    calls = _run(monkeypatch, {
        'hostname': '', 'port': 5340, 'master_key': 'k', 'dial_update_period': 200,
    })
    assert calls == [(5340, '')]
