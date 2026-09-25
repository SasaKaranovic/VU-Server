"""Shared fixtures: a fake clock, and bare driver and handler objects built without hardware."""
import os
import sys
import types
from threading import Lock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_dial_handler
from dial_driver import DialSerialDriver
from server_dial_handler import ServerDialHandler


@pytest.fixture
def fake_clock(monkeypatch):
    """Freeze the handler's clock at 1000.0. Advance it by assigning to clock[0]."""
    clock = [1000.0]
    monkeypatch.setattr(server_dial_handler, 'time', lambda: clock[0])
    return clock


@pytest.fixture
def make_serial():
    """Build a `cls` instance talking to `port`, bypassing real serial setup."""
    def make(cls=DialSerialDriver, port=None):
        obj = object.__new__(cls)
        obj.lock = Lock()
        obj.port_info = types.SimpleNamespace(name="FAKE0", description="fake serial port")
        obj.port = port
        obj.dials = {}
        return obj
    return make


@pytest.fixture
def bare_driver(make_serial):
    """A DialSerialDriver with no port and no dials."""
    return make_serial()


@pytest.fixture
def make_handler():
    """Build a ServerDialHandler on `driver` with dial 'AAA' at index '0', value and backlight pending."""
    def make(driver=None):
        handler = object.__new__(ServerDialHandler)
        handler.dial_driver = driver
        handler.dials = {'AAA': {
            'uid': 'AAA', 'index': '0', 'image_changed': False,
            'value': 50, 'value_changed': True,
            'value_fail_count': 0, 'value_retry_after': 0, 'value_unresponsive': False,
            'backlight': {'red': 100, 'green': 0, 'blue': 0, 'white': 0}, 'backlight_changed': True,
            'backlight_fail_count': 0, 'backlight_retry_after': 0, 'backlight_unresponsive': False,
        }}
        return handler
    return make
