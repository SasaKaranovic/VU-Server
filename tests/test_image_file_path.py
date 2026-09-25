"""A dial's `image_file` must be an absolute path, because a reset hands it to the driver, which opens it from any CWD."""
import os

import server_dial_handler
from dial_driver import DialSerialDriver
from server_dial_handler import dial_image_file


def test_startup_image_file_is_an_absolute_path():
    path = dial_image_file('DOESNOTEXIST')
    assert os.path.isabs(path), f"got a bare filename: {path!r}"
    assert os.path.basename(path) == 'img_blank'


def test_startup_image_file_points_at_the_uploaded_image(tmp_path, monkeypatch):
    monkeypatch.setattr(server_dial_handler, 'UPLOAD_DIR', str(tmp_path), raising=False)
    (tmp_path / 'img_AAA').write_bytes(b'png')

    assert dial_image_file('AAA') == str(tmp_path / 'img_AAA')


def test_startup_image_file_falls_back_to_blank_in_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(server_dial_handler, 'UPLOAD_DIR', str(tmp_path), raising=False)

    assert dial_image_file('AAA') == str(tmp_path / 'img_blank')


def test_driver_can_send_the_startup_image_file():
    # End to end: whatever the handler records at startup must be something
    # DialSerialDriver.display_send_image can find on disk. `img_blank` ships
    # in upload/, so the fallback path must resolve to it.
    image_file = dial_image_file('DOESNOTEXIST')

    driver = object.__new__(DialSerialDriver)
    sent = {}
    def record(device, data):
        sent['data'] = data
        return True

    driver.display_send_image_data = record

    assert driver.display_send_image(0, image_file) is True, (
        f"driver could not open {image_file!r} from cwd {os.getcwd()!r}")
    # 200x144 packs to 200 columns of 18 bytes.
    assert len(sent['data']) == 200 * 144 // 8
