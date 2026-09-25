"""A percent-set reads its own hub ACK, so the next command never parses a leftover `<03...` line as its reply."""
import pytest


class _FakeHub:
    """A gauge hub that ACKs every command, echoing the command byte.

    An ACK becomes readable only on the next read, like bytes still on the wire:
    invisible to `in_waiting` and untouched by `reset_input_buffer()`.
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


@pytest.fixture
def driver(make_serial):
    """A DialSerialDriver talking to the fake hub, with dial 'AAA' at index 0."""
    driver = make_serial(port=_FakeHub())
    driver.dials = {0: 'AAA'}
    return driver


def test_percent_set_consumes_its_own_ack(driver):
    driver.dial_single_set_percent(0, 59)

    assert driver.port.unread_lines() == 0, (
        "percent-set left its ACK unread; the next command will consume it")


def test_backlight_after_percent_set_parses_its_own_reply(driver):
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


def test_parse_response_rejects_a_reply_for_a_different_command(driver):
    # The hub echoes the command byte, so a mismatched echo is detectable.
    result = driver._parseResponse(['<0305000400000000'], expected_cmd=0x13)

    assert result is False, "a cmd 0x03 reply must not satisfy a cmd 0x13 request"


def test_parse_response_accepts_the_matching_reply_among_stale_lines(driver):
    result = driver._parseResponse(
        ['<0305000400000000', '<1305000400000000'], expected_cmd=0x13)

    assert result is True
