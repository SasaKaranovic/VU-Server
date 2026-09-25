"""`server.hostname` from config.yaml sets the listen address, and an empty hostname binds all interfaces."""
import types

import pytest

import server


class _Listened(Exception):
    """Ends run_forever once the bind address is known."""


class _FakeApp:
    """Records what Application.listen() is asked to bind."""
    listen_calls = []

    def __init__(self, *args, **kwargs):
        pass

    def listen(self, port, address=None, **kwargs):
        _FakeApp.listen_calls.append((port, address))
        raise _Listened


def _service(server_cfg):
    service = object.__new__(server.Dial_API_Service)
    service.handlers = []
    service.serial_executor = None
    service.dial_handler = types.SimpleNamespace(periodic_dial_update=lambda: None)
    service.config = types.SimpleNamespace(get_server_config=lambda: server_cfg)
    return service


def _run(monkeypatch, server_cfg):
    _FakeApp.listen_calls = []
    monkeypatch.setattr(server, 'Application', _FakeApp)
    with pytest.raises(_Listened):
        _service(server_cfg).run_forever()
    return _FakeApp.listen_calls


def test_run_forever_binds_to_configured_hostname(monkeypatch):
    calls = _run(monkeypatch, {
        'hostname': '127.0.0.1', 'port': 5340, 'master_key': 'k', 'dial_update_period': 200,
    })
    assert calls == [(5340, '127.0.0.1')], (
        f"expected listen(5340, address='127.0.0.1'); got {calls}")


def test_run_forever_binds_all_interfaces_when_hostname_is_empty(monkeypatch):
    # Tornado treats an empty address as all interfaces.
    calls = _run(monkeypatch, {
        'hostname': '', 'port': 5340, 'master_key': 'k', 'dial_update_period': 200,
    })
    assert calls == [(5340, '')]
