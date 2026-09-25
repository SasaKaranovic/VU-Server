"""Tests for DialSerialDriver image packing, command framing and display updates."""
from PIL import Image

from dial_driver import DialSerialDriver
from dials.Comms_Hub_Server import hub_commands


def _driver():
    driver = object.__new__(DialSerialDriver)
    driver.dials = {}
    return driver


def test_img_to_binary_packs_columns_top_pixel_first(tmp_path):
    # Column 0 lights rows 0 and 9; column 1 lights row 7. Height 10 leaves a
    # 2-bit tail per column, carried in the low bits of its last byte.
    img = Image.new("L", (2, 10), 0)
    img.putpixel((0, 0), 255)
    img.putpixel((0, 9), 200)
    img.putpixel((1, 7), 128)
    img.putpixel((1, 8), 127)
    path = tmp_path / "img"
    img.save(path, format="PNG")

    assert DialSerialDriver.img_to_binary(str(path)) == bytes([0x80, 0x01, 0x01, 0x00])


def test_img_to_binary_returns_none_for_unreadable_file(tmp_path):
    bad = tmp_path / "img"
    bad.write_bytes(b"not an image")

    assert DialSerialDriver.img_to_binary(str(bad)) is None
    assert DialSerialDriver.img_to_binary(str(tmp_path / "missing")) is None


def test_send_command_frames_payload_as_uppercase_hex():
    driver = _driver()
    sent = []
    driver.serial_transaction = lambda payload, read_timeout: sent.append(payload) or []

    driver._send_cmd_with_uin32('3', 0x14, 70000)

    assert sent == ['>140200050300011170']


def test_update_display_skips_show_when_image_cannot_be_converted(tmp_path):
    driver = _driver()
    sent = []
    driver._sendCommand = lambda cmd, *a, **k: sent.append(cmd) or True

    assert driver.update_display('0', imageFile=str(tmp_path / "missing")) is False
    assert hub_commands.COMM_CMD_DISPLAY_SHOW_IMG not in sent
