"""Hub error statuses must be reported as failures, not silently as success.

`DialSerialDriver._parseResponse` slices the data-type field out of the reply
as a two-character hex *string* (e.g. `'05'`) and compared it directly to
`hub_data_types.COMM_DATA_STATUS_CODE`, which is the *int* `0x05`. They are
never equal, so `_checkStatus` was unreachable and every status-code reply
fell through to `return ret['data']` -- the raw status string. `'00000001'`
(GAUGE_STATUS_FAIL) and `'00000002'` (GAUGE_STATUS_BUSY) are truthy, so a
NAK'd backlight write, percent-set, easing set, calibrate or reset was logged
as delivered and the retry/backoff machinery only ever fired on timeouts.
"""
import types
from threading import Lock

from dial_driver import DialSerialDriver
from dials.Comms_Hub_Server import hub_commands, hub_data_types, hub_status_codes


def _driver():
    """A DialSerialDriver with the REAL protocol constants and no serial port."""
    driver = object.__new__(DialSerialDriver)
    driver.dials = {}
    driver.commands = hub_commands()
    driver.data_type = hub_data_types()
    driver.status_codes = hub_status_codes()
    return driver


def test_ok_status_reply_is_true():
    driver = _driver()
    assert driver._parseResponse(['<1305000400000000'], expected_cmd=0x13) is True


def test_fail_status_reply_is_false():
    driver = _driver()
    # GAUGE_STATUS_FAIL: previously came back as the truthy string '00000001'.
    assert driver._parseResponse(['<1305000400000001'], expected_cmd=0x13) is False


def test_busy_status_reply_is_false():
    driver = _driver()
    # GAUGE_STATUS_BUSY: previously came back as the truthy string '00000002'.
    assert driver._parseResponse(['<0305000400000002'], expected_cmd=0x03) is False


def test_data_reply_still_returns_payload():
    driver = _driver()
    # A non-status reply (here COMM_DATA_SINGLE_VALUE=0x02) must still hand
    # back its payload untouched -- e.g. the device map or a UID.
    assert driver._parseResponse(['<0702000201'], expected_cmd=0x07) == '01'


def test_malformed_status_payload_is_false():
    driver = _driver()
    # A status-code reply with a truncated/garbage payload must not raise.
    assert driver._parseResponse(['<130500'], expected_cmd=0x13) is False
    assert driver._parseResponse(['<13050004ZZZZZZZZ'], expected_cmd=0x13) is False


# -- end to end through serial_transaction with a NAKing hub ------------------

class _FakePortInfo:
    name = "FAKE0"
    description = "fake gauge hub"


class _NakHub:
    """A hub that answers every command with GAUGE_STATUS_FAIL."""
    is_open = True

    def __init__(self):
        self._readable = []

    def write(self, data):
        cmd = data.decode()[1:3]
        self._readable.append(f"<{cmd}05000400000001\r\n".encode())
        return len(data)

    @property
    def in_waiting(self):
        return sum(len(line) for line in self._readable)

    def readline(self):
        return self._readable.pop(0) if self._readable else b''

    def reset_input_buffer(self):
        self._readable.clear()

    def reset_output_buffer(self):
        pass


def test_backlight_write_nakked_by_hub_returns_false():
    driver = _driver()
    driver.lock = Lock()
    driver.flush_on_write = True
    driver.serialPrefix = ''
    driver.serialSuffix = '\r\n'
    driver.debug_uart = False
    driver.port_info = _FakePortInfo()
    driver.port = _NakHub()
    driver.dials = {0: {'index': '0', 'uid': 'AAA', 'value': 0, 'rgbw': [0, 0, 0, 0]}}

    assert driver.dial_set_backlight(0, 100, 0, 0, 0) is False, (
        "hub NAK must surface as a failed write so the handler retries it")
