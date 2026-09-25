"""Tests for SerialHardware.serial_transaction and its read helpers."""
from unittest.mock import MagicMock

import pytest
import serial as _serial

import serial_driver
from serial_driver import SerialHardware


class _FakePort:
    """Serial-port stand-in holding stale RX bytes and recording writes."""
    is_open = True

    def __init__(self, stale=b''):
        self._rx = stale
        self.written = []

    @property
    def in_waiting(self):
        return len(self._rx)

    def readline(self):
        line, sep, self._rx = self._rx.partition(b'\n')
        return line + sep

    def reset_input_buffer(self):
        self._rx = b''

    def write(self, data):
        self.written.append(data)
        return len(data)


@pytest.fixture
def bare_serial(make_serial):
    """Build a SerialHardware wired to a fake port."""
    return lambda port: make_serial(SerialHardware, port)


def test_serial_transaction_returns_only_the_fresh_response(bare_serial):
    s = bare_serial(_FakePort(stale=b'<99009999STALE\r\n'))
    s.read_until_response = lambda timeout=5: ['<01000000AA']

    assert s.serial_transaction('>0100') == ['<01000000AA']
    assert s.port.written == [b'>0100\r\n']


def test_stale_line_not_surfaced_when_no_fresh_response_arrives(bare_serial):
    # A timed-out command must not take a leftover `<...>` line as its reply.
    s = bare_serial(_FakePort(stale=b'<99009999STALE\r\n'))

    assert s.serial_transaction('>0100', read_timeout=0) == []


def test_partial_stale_line_is_discarded_without_reading(bare_serial):
    # An unterminated line would otherwise make readline() wait out its timeout.
    port = _FakePort(stale=b'<9900')
    port.readline = MagicMock(side_effect=AssertionError("stale bytes must not be read"))
    s = bare_serial(port)
    s.read_until_response = lambda timeout=5: ['<01000000AA']

    assert s.serial_transaction('>0100') == ['<01000000AA']


def test_stale_bytes_are_not_logged_as_errors(monkeypatch, bare_serial):
    fake_logger = MagicMock()
    monkeypatch.setattr(serial_driver, "logger", fake_logger)
    s = bare_serial(_FakePort(stale=b'<99\r\n'))
    s.read_until_response = lambda timeout=5: ['<01000000AA']

    s.serial_transaction('>0100')

    assert fake_logger.error.call_count == 0


class _DisconnectPort(_FakePort):
    """A port whose readline() raises, like an unplug mid-read."""

    def readline(self):
        raise _serial.SerialException("read failed: [Errno 5] Input/output error")


def test_handle_serial_read_survives_device_disconnect(monkeypatch, bare_serial):
    # Propagating would kill the serial executor thread; the errno text must still reach the log.
    fake_logger = MagicMock()
    monkeypatch.setattr(serial_driver, "logger", fake_logger)
    s = bare_serial(_DisconnectPort())

    assert s.handle_serial_read() is None
    assert "[Errno 5]" in fake_logger.error.call_args.args[0]


def test_read_until_response_logs_no_error_on_successful_read(monkeypatch, bare_serial):
    fake_logger = MagicMock()
    monkeypatch.setattr(serial_driver, "logger", fake_logger)
    s = bare_serial(_FakePort(stale=b'noise\r\n<01000000AA\r\n'))

    assert s.read_until_response(timeout=1) == ['noise', '<01000000AA']
    assert fake_logger.error.call_count == 0


def test_serial_transaction_releases_lock_when_write_fails(bare_serial):
    port = _FakePort()
    port.write = MagicMock(side_effect=_serial.SerialTimeoutException("Write timeout"))
    s = bare_serial(port)

    with pytest.raises(_serial.SerialTimeoutException):
        s.serial_transaction('>0100')

    # A leaked lock would make this acquire block.
    assert s.lock.acquire(timeout=1) is True
    s.lock.release()
