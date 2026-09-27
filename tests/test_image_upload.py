import json
import zlib

import pytest
import tornado.testing
import tornado.web

from server import Device_Set_Image

BOUNDARY = 'vu1boundary'


def _multipart(body):
    return (f'--{BOUNDARY}\r\n'
            'Content-Disposition: form-data; name="imgfile"; filename="img.png"\r\n'
            'Content-Type: image/png\r\n\r\n').encode() + body + f'\r\n--{BOUNDARY}--\r\n'.encode()


class FakeDialHandler:
    def __init__(self):
        self.images = []

    def dial_set_image(self, dial_uid, image_file):
        self.images.append((dial_uid, image_file))
        return True


class FakeConfig:
    def is_valid_api_key(self, key):
        return key == 'testkey'

    def api_key_has_access_to_dial(self, api_key, gaugeUID):
        return True


class TmpDirSetImage(Device_Set_Image):
    """Device_Set_Image writing into a test-supplied upload directory."""
    def initialize(self, upload_path, **kwargs):
        super().initialize(**kwargs)
        self.upload_path = upload_path


class ImageUploadTestCase(tornado.testing.AsyncHTTPTestCase):
    @pytest.fixture(autouse=True)
    def _upload_dir(self, tmp_path):
        self.upload_dir = tmp_path

    def get_app(self):
        self.fake_handler = FakeDialHandler()
        handlers_config = {"handler": self.fake_handler, "config": FakeConfig(),
                           "upload_path": str(self.upload_dir)}
        return tornado.web.Application([
            (r"/api/v0/dial/([0-9A-F]*?)/image/set", TmpDirSetImage, handlers_config),
        ])

    def _upload(self, body):
        response = self.fetch(
            "/api/v0/dial/ABC123/image/set?key=testkey", method='POST', body=_multipart(body),
            headers={'Content-Type': f'multipart/form-data; boundary={BOUNDARY}'})
        return response, json.loads(response.body)

    def test_identical_image_leaves_no_temp_file(self):
        (self.upload_dir / 'img_ABC123').write_bytes(b'same')

        response, body = self._upload(b'same')

        assert response.code == 200
        assert 'Skipping' in body['message']
        assert sorted(p.name for p in self.upload_dir.iterdir()) == ['img_ABC123']
        assert self.fake_handler.images == []

    def test_first_image_with_zero_crc_is_stored(self):
        # get_file_crc reports a missing file as "00000000", so a first upload
        # whose real CRC-32 is 0 looked identical to "no image".
        image = b'png\r\t\xc1\xee'
        assert zlib.crc32(image) == 0

        response, _ = self._upload(image)

        assert response.code == 201
        assert (self.upload_dir / 'img_ABC123').read_bytes() == image
        assert self.fake_handler.images == [('ABC123', str(self.upload_dir / 'img_ABC123'))]
