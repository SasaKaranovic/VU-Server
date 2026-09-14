"""Tests for SerialHardware.serial_transaction.

Bug #2: stale bytes left in the RX buffer from a previous/aborted transaction
were drained and logged as "discarding N stale buffered line(s)", but then
concatenated onto the return value (`lines = rx_lines + lines`). When the real
read produced no `<`-prefixed reply, a leftover `<...>` line then got parsed as
*this* command's response -- a wrong, misattributed hardware reply.
"""
from threading import Lock
from unittest.mock import MagicMock

import serial as _serial

import serial_driver
from serial_driver import SerialHardware


class _FakePortInfo:
    """Stand-in for pyserial's ListPortInfo, for error-message formatting."""
    name = "FAKE0"
    description = "fake serial port"


class _FakePort:
    """Minimal serial-port stand-in exposing just what serial_transaction reads."""
    is_open = True

    def __init__(self, buffered_lines):
        self._buffer = [line.encode() for line in buffered_lines]

    @property
    def in_waiting(self):
        return len(self._buffer)

    def readline(self):
        return self._buffer.pop(0) if self._buffer else b''


def _bare_serial(buffered_lines):
    """A SerialHardware wired to a fake port, bypassing real serial setup."""
    s = object.__new__(SerialHardware)
    s.lock = Lock()
    s.flush_on_write = False
    s.debug_uart = False
    s.port_info = _FakePortInfo()
    s.port = _FakePort(buffered_lines)
    # Sending always "succeeds"; response content is supplied per-test.
    s.handle_serial_send = lambda payload: True
    return s


def test_serial_transaction_returns_only_the_fresh_response():
    s = _bare_serial(buffered_lines=['<99009999STALE'])  # leftover from before
    s.read_until_response = lambda timeout=5: ['<01000000AA']  # this command's reply

    result = s.serial_transaction('>0100')

    assert result == ['<01000000AA']
    assert '<99009999STALE' not in result


def test_stale_line_not_surfaced_when_no_fresh_response_arrives():
    # The dangerous case: the current command times out with no reply, but a
    # stale `<...>` line is still sitting in the buffer. It must NOT be returned
    # as though it were this command's response.
    s = _bare_serial(buffered_lines=['<99009999STALE'])
    s.read_until_response = lambda timeout=5: []  # timed out, nothing fresh

    result = s.serial_transaction('>0100')

    assert result == []


def test_ignore_response_does_not_return_stale_lines():
    s = _bare_serial(buffered_lines=['<99009999STALE'])

    result = s.serial_transaction('>0100', ignore_response=True)

    assert result == []


# --- B1: handle_serial_read must survive a mid-read hardware failure ----------
class _DisconnectPort:
    """A port that raises SerialException from readline(), like an unplug mid-read."""
    is_open = True

    @property
    def in_waiting(self):
        return 0

    def readline(self):
        raise _serial.SerialException("device disconnected")


def test_handle_serial_read_survives_device_disconnect():
    # readline() raises SerialException when the device drops mid-read (NOT the
    # write-only SerialTimeoutException the old code guarded against). It must be
    # caught and reported as "no line", never propagated out of the read loop
    # where it would kill the serial executor thread.
    s = _bare_serial(buffered_lines=[])
    s.port = _DisconnectPort()

    assert s.handle_serial_read() is None


# --- B7: the stale-drain loop must not spin on a partial (unterminated) line ---
class _PartialLinePort:
    """Raw bytes are waiting but they never form a complete line.

    Real pyserial behaviour: in_waiting reports buffered bytes, but readline()
    times out returning b'' when no line terminator has arrived yet. The old
    ``while self.port.in_waiting`` drain re-read forever because in_waiting
    stayed positive while every read came back empty.
    """
    is_open = True

    def __init__(self):
        self.readline_calls = 0
        self._cleared = False

    @property
    def in_waiting(self):
        return 0 if self._cleared else 4  # 4 buffered bytes, no terminator

    def readline(self):
        self.readline_calls += 1
        if self.readline_calls > 20:
            raise AssertionError(
                "stale-drain spun: readline called >20 times on a partial line")
        return b''  # never a complete line

    def reset_input_buffer(self):
        self._cleared = True


def test_stale_drain_does_not_spin_on_partial_line():
    s = _bare_serial(buffered_lines=[])
    s.port = _PartialLinePort()
    s.read_until_response = lambda timeout=5: ['<01000000AA']

    result = s.serial_transaction('>0100')

    assert result == ['<01000000AA']
    # Broke out of the drain immediately instead of re-reading the partial line.
    assert s.port.readline_calls <= 2


# --- B3: benign pre-write bytes must not be logged at ERROR level -------------
class _WritablePort:
    """Port stand-in for handle_serial_send: reports pending bytes and accepts writes."""
    is_open = True

    def __init__(self, pending=0):
        self._pending = pending
        self.written = []
        self.reset_calls = 0

    @property
    def in_waiting(self):
        return self._pending

    def reset_input_buffer(self):
        self.reset_calls += 1
        self._pending = 0

    def write(self, data):
        self.written.append(data)
        return len(data)


def _send_serial(port, flush_on_write=True):
    """A SerialHardware wired to a writable fake port for exercising handle_serial_send."""
    s = object.__new__(SerialHardware)
    s.flush_on_write = flush_on_write
    s.serialPrefix = ''
    s.serialSuffix = '\r\n'
    s.debug_uart = False
    s.port_info = _FakePortInfo()
    s.port = port
    return s


def test_handle_serial_send_does_not_error_on_expected_pending_bytes(monkeypatch):
    # serial_transaction already drained the RX buffer before calling send, so a
    # pre-write flush is routine hygiene -- it must not be logged at ERROR level.
    fake_logger = MagicMock()
    monkeypatch.setattr(serial_driver, "logger", fake_logger)
    port = _WritablePort(pending=2)
    s = _send_serial(port)

    assert s.handle_serial_send('>0100') is True
    assert fake_logger.error.call_count == 0
    assert port.written == [b'>0100\r\n']


# --- B2: read_until_response logs no spurious ERROR during normal operation ----
def test_read_until_response_logs_no_error_on_successful_read(monkeypatch):
    fake_logger = MagicMock()
    monkeypatch.setattr(serial_driver, "logger", fake_logger)
    s = _bare_serial(buffered_lines=[])
    replies = iter(['<01000000AA'])
    s.handle_serial_read = lambda: next(replies, '')

    result = s.read_until_response(timeout=1)

    assert result == ['<01000000AA']
    assert fake_logger.error.call_count == 0


# --- B6: the lock is always released, even when the send fails -----------------
def test_serial_transaction_releases_lock_when_send_fails():
    s = _bare_serial(buffered_lines=[])
    s.handle_serial_send = lambda payload: False  # send failure -> raises inside

    try:
        s.serial_transaction('>0100')
    except _serial.SerialException:
        pass

    # If the lock leaked, this second acquire would block forever.
    assert s.lock.acquire(timeout=1) is True
    s.lock.release()
