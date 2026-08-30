"""A dial's `image_file` must be a path the driver can actually open.

`_check_upload_for_dial_image` stored a bare filename (`img_<uid>` or
`img_blank`) in `dial['image_file']`. Nothing reads it until the dial is
re-armed by `/reset` or `/reset_all`, at which point `update_display` clears
the eink display, `display_send_image` does `os.path.exists('img_<uid>')`
relative to the process CWD, finds nothing, and returns False -- and the
display is then shown blank. Only images uploaded through the API in the
current process (stored as absolute paths) survived a reset.
"""
import os

import server_dial_handler
from dial_driver import DialSerialDriver
from server_dial_handler import ServerDialHandler


def _handler():
    return object.__new__(ServerDialHandler)


def test_startup_image_file_is_an_absolute_path():
    path = _handler()._check_upload_for_dial_image('DOESNOTEXIST')
    assert os.path.isabs(path), f"got a bare filename: {path!r}"
    assert os.path.basename(path) == 'img_blank'


def test_startup_image_file_points_at_the_uploaded_image(tmp_path, monkeypatch):
    monkeypatch.setattr(server_dial_handler, 'UPLOAD_DIR', str(tmp_path), raising=False)
    (tmp_path / 'img_AAA').write_bytes(b'png')

    assert _handler()._check_upload_for_dial_image('AAA') == str(tmp_path / 'img_AAA')


def test_startup_image_file_falls_back_to_blank_in_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(server_dial_handler, 'UPLOAD_DIR', str(tmp_path), raising=False)

    assert _handler()._check_upload_for_dial_image('AAA') == str(tmp_path / 'img_blank')


def test_driver_can_send_the_startup_image_file():
    # End to end: whatever the handler records at startup must be something
    # DialSerialDriver.display_send_image can find on disk. `img_blank` ships
    # in upload/, so the fallback path must resolve to it.
    image_file = _handler()._check_upload_for_dial_image('DOESNOTEXIST')

    driver = object.__new__(DialSerialDriver)
    sent = {}
    driver.img_to_binary = lambda path, flatten=True: [1, 2, 3]
    def record(device, data):
        sent['data'] = data
        return True

    driver.display_send_image_data = record

    assert driver.display_send_image(0, image_file) is True, (
        f"driver could not open {image_file!r} from cwd {os.getcwd()!r}")
    assert sent['data'] == [1, 2, 3]
