"""COMM_CMD_SET_DIAL_PERC_SINGLE must consume its own hub ACK.

`dial_single_set_percent` was sent with `ignore_response=True` on the premise
that the hub never ACKs a percent-set. It does: captured traces show
`>030400020000` answered by `<0305000400000000` ~15-19ms later. Because nobody
read it, that ACK stayed in the RX buffer and was then handed to whichever
command ran next -- e.g. a backlight write (cmd 0x13) returning the percent-set's
`<0305...` line instead of its own `<1305...`:

    Sending `>030400020000`          <- percent-set, response ignored
    Sending `>130300050000000000`    <- backlight
    <0305000400000000                <- cmd 03 reply parsed as the backlight reply

When the bus was instead idle long enough for the ACK to land before the next
command, it surfaced as "discarding 1 stale buffered line(s)". Same orphaned
ACK, two different symptoms -- which is why it looked intermittent.
"""
import types

import pytest

from dial_driver import DialSerialDriver


class _FakePortInfo:
    name = "FAKE0"
    description = "fake gauge hub"


class _FakeHub:
    """A gauge hub that ACKs every command, echoing the command byte.

    ACKs land in `_inflight` on write and only become readable on the next
    read -- modelling the real ~15-19ms turnaround, during which the bytes are
    still on the wire and therefore invisible to `in_waiting` and unaffected by
    `reset_input_buffer()`.
    """
    is_open = True

    def __init__(self):
        self._inflight = []
        self._readable = []

    def _write_line(self, payload):
        cmd = payload[1:3]  # commands are '>CCTT....'
        self._inflight.append(f"<{cmd}05000400000000\r\n".encode())

    def write(self, data):
        self._write_line(data.decode().strip())
        return len(data)

    def _deliver(self):
        self._readable.extend(self._inflight)
        self._inflight.clear()

    @property
    def in_waiting(self):
        # Bytes still on the wire are not yet buffered by the OS.
        return sum(len(line) for line in self._readable)

    def readline(self):
        self._deliver()
        return self._readable.pop(0) if self._readable else b''

    def reset_input_buffer(self):
        self._readable.clear()

    def reset_output_buffer(self):
        pass

    def unread_lines(self):
        return len(self._readable) + len(self._inflight)


def _hub_driver():
    """A DialSerialDriver talking to the fake hub, bypassing real serial setup."""
    from threading import Lock

    driver = object.__new__(DialSerialDriver)
    driver.lock = Lock()
    driver.flush_on_write = True
    driver.serialPrefix = ''
    driver.serialSuffix = '\r\n'
    driver.debug_uart = False
    driver.port_info = _FakePortInfo()
    driver.port = _FakeHub()
    driver.dials = {0: {'index': '0', 'uid': 'AAA', 'value': 0, 'rgbw': [0, 0, 0, 0]}}
    driver.commands = types.SimpleNamespace(
        COMM_CMD_SET_DIAL_PERC_SINGLE=0x03,
        COMM_CMD_SET_RGB_BACKLIGHT=0x13,
    )
    driver.data_type = types.SimpleNamespace(
        COMM_DATA_MULTIPLE_VALUE=0x03,
        COMM_DATA_KEY_VALUE_PAIR=0x04,
        COMM_DATA_STATUS_CODE=0x05,
    )
    driver.status_codes = types.SimpleNamespace(GAUGE_STATUS_OK=0x0000)
    return driver


def test_percent_set_consumes_its_own_ack():
    # The root cause: the hub ACKs a percent-set, so the transaction that sent
    # it must be the one that reads it. Leaving it buffered desynchronises every
    # later command on the shared port.
    driver = _hub_driver()

    driver.dial_single_set_percent(0, 59)

    assert driver.port.unread_lines() == 0, (
        "percent-set left its ACK unread; the next command will consume it")


def test_backlight_after_percent_set_parses_its_own_reply():
    # The observed symptom: cmd 0x13's reply must be a `<13...` line, never the
    # `<03...` ACK orphaned by the preceding percent-set.
    driver = _hub_driver()
    seen = []
    real_parse = driver._parseResponse

    def spy(response, *args, **kwargs):
        seen.extend(response)
        return real_parse(response, *args, **kwargs)

    driver._parseResponse = spy

    driver.dial_single_set_percent(0, 59)
    seen.clear()  # only inspect what the backlight write parses
    driver.dial_set_backlight(0, 0, 100, 0, 0)

    matched = [line for line in seen if line.startswith('<')]
    assert matched, "backlight write got no reply at all"
    assert matched[0].startswith('<13'), (
        f"backlight write parsed a foreign reply: {matched[0]!r}")


def test_parse_response_rejects_a_reply_for_a_different_command():
    # Defence in depth: the hub echoes the command byte, so a mismatched echo is
    # detectable. Accepting any `<` line is what let the desync stay silent.
    driver = _hub_driver()

    result = driver._parseResponse(['<0305000400000000'], expected_cmd=0x13)

    assert result is False, "a cmd 0x03 reply must not satisfy a cmd 0x13 request"


def test_parse_response_accepts_the_matching_reply_among_stale_lines():
    driver = _hub_driver()

    result = driver._parseResponse(
        ['<0305000400000000', '<1305000400000000'], expected_cmd=0x13)

    assert result is True
