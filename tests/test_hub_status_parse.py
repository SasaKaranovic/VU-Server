"""Hub status replies parse to a bool, so a NAK surfaces as a failed write rather than a truthy payload string."""


def test_ok_status_reply_is_true(bare_driver):
    assert bare_driver._parseResponse(['<1305000400000000'], expected_cmd=0x13) is True


def test_fail_status_reply_is_false(bare_driver):
    # GAUGE_STATUS_FAIL
    assert bare_driver._parseResponse(['<1305000400000001'], expected_cmd=0x13) is False


def test_busy_status_reply_is_false(bare_driver):
    # GAUGE_STATUS_BUSY
    assert bare_driver._parseResponse(['<0305000400000002'], expected_cmd=0x03) is False


def test_data_reply_still_returns_payload(bare_driver):
    # A COMM_DATA_SINGLE_VALUE reply, such as the device map or a UID, keeps its payload.
    assert bare_driver._parseResponse(['<0702000201'], expected_cmd=0x07) == '01'


def test_malformed_status_payload_is_false(bare_driver):
    assert bare_driver._parseResponse(['<130500'], expected_cmd=0x13) is False
    assert bare_driver._parseResponse(['<13050004ZZZZZZZZ'], expected_cmd=0x13) is False


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


def test_backlight_write_nakked_by_hub_returns_false(make_serial):
    driver = make_serial(port=_NakHub())
    driver.dials = {0: 'AAA'}

    assert driver.dial_set_backlight(0, 100, 0, 0, 0) is False, (
        "hub NAK must surface as a failed write so the handler retries it")
