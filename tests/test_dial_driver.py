"""DialSerialDriver logic without a hub: image packing, command framing, bus scan and backlight writes."""
from PIL import Image

from dial_driver import DialSerialDriver
from dials.Comms_Hub_Server import hub_commands


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


def test_send_command_frames_payload_as_uppercase_hex(bare_driver):
    sent = []
    bare_driver.serial_transaction = lambda payload, read_timeout: sent.append(payload) or []

    bare_driver._send_cmd_with_uin32('3', 0x14, 70000)

    assert sent == ['>140200050300011170']


def test_update_display_skips_show_when_image_cannot_be_converted(bare_driver, tmp_path):
    sent = []
    bare_driver._sendCommand = lambda cmd, *a, **k: sent.append(cmd) or True

    assert bare_driver.update_display('0', imageFile=str(tmp_path / "missing")) is False
    assert hub_commands.COMM_CMD_DISPLAY_SHOW_IMG not in sent


def test_get_dial_list_rescan_drops_offline_dials(bare_driver):
    bare_driver.dials = {0: 'AAA', 1: 'BBB'}
    bare_driver.bus_rescan = lambda: True
    # Only index 0 reports online: one byte, value 1.
    bare_driver._sendCommand = lambda *a, **k: "01"
    bare_driver.dial_get_uid = lambda index: 'AAA'

    assert bare_driver.get_dial_list(rescan=True) == {0: 'AAA'}
    assert bare_driver.dials == {0: 'AAA'}


def test_dial_set_backlight_unknown_dial_returns_false(bare_driver):
    assert bare_driver.dial_set_backlight('9', 1, 2, 3, 4) is False


def test_dial_set_backlight_uses_bounded_read_timeout(bare_driver):
    # The default 5 s wait for an ACK would freeze the IOLoop when a dial goes silent.
    bare_driver.dials = {0: 'AAA'}
    captured = {}

    def fake_txn(payload, read_timeout=None):
        captured['read_timeout'] = read_timeout
        return []

    bare_driver.serial_transaction = fake_txn

    bare_driver.dial_set_backlight(0, 1, 2, 3, 4)

    assert captured['read_timeout'] == DialSerialDriver.BACKLIGHT_READ_TIMEOUT
    assert captured['read_timeout'] < 5
