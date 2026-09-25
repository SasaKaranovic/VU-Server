"""SIGTERM and SIGINT blank the dials on the serial worker, after the last periodic update, and return promptly."""
import asyncio
import signal
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

import pytest

import server


@pytest.fixture(autouse=True)
def restore_signal_handlers():
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


class FakeApp:
    def __init__(self, *args, **kwargs):
        pass

    def listen(self, port, address=None, **kwargs):
        return types.SimpleNamespace(stop=lambda: None)


def _on_worker():
    return threading.current_thread().name.startswith('serial')


def _service(events, set_percent=None):
    service = object.__new__(server.Dial_API_Service)
    service.handlers = []
    service.serial_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='serial')
    service.dial_handler = types.SimpleNamespace(
        periodic_dial_update=lambda: events.append(('update', _on_worker())))
    service.dial_driver = types.SimpleNamespace(
        dials={0: 'AAA'},
        dial_single_set_percent=set_percent or (lambda dial, value: events.append(('percent', dial, value, _on_worker()))),
        dial_set_backlight=lambda device, **rgbw: events.append(('backlight', device, rgbw, _on_worker())),
    )
    service.config = types.SimpleNamespace(get_server_config=lambda: {
        'hostname': '127.0.0.1', 'port': 0, 'master_key': 'k', 'dial_update_period': 10,
    })
    return service


def _serve_until(service, sig, after=0.2):
    async def run():
        asyncio.get_running_loop().call_later(after, signal.raise_signal, sig)
        await service._serve()

    start = time.monotonic()
    asyncio.run(run())
    return time.monotonic() - start - after


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT])
def test_signal_blanks_dials_on_the_worker_after_the_last_update(monkeypatch, sig):
    monkeypatch.setattr(server, 'Application', FakeApp)
    events = []
    service = _service(events)

    assert _serve_until(service, sig) < 1
    assert ('update', True) in events
    assert events[-2:] == [
        ('percent', 0, 0, True),
        ('backlight', 0, {'red': 0, 'green': 0, 'blue': 0, 'white': 0}, True),
    ]
    with pytest.raises(RuntimeError):
        service.serial_executor.submit(service.dial_handler.periodic_dial_update)


def test_hung_bus_does_not_hold_up_shutdown(monkeypatch):
    monkeypatch.setattr(server, 'Application', FakeApp)
    monkeypatch.setattr(server, 'SHUTDOWN_TIMEOUT', 0.2)
    release = threading.Event()
    service = _service([], set_percent=lambda dial, value: release.wait(5))

    try:
        assert _serve_until(service, signal.SIGTERM) < 1
    finally:
        release.set()
