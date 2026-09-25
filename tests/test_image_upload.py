"""Image upload replaces `img_<uid>` atomically, skips identical content, and leaves no temp file."""
import json
import zlib

import pytest
import tornado.testing
import tornado.web

import server
import server_dial_handler

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


class ImageUploadTestCase(tornado.testing.AsyncHTTPTestCase):
    @pytest.fixture(autouse=True)
    def _upload_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server_dial_handler, 'UPLOAD_DIR', str(tmp_path))
        monkeypatch.setattr(server, 'UPLOAD_DIR', str(tmp_path))
        (tmp_path / 'img_blank').write_bytes(b'blank')
        self.upload_dir = tmp_path

    def get_app(self):
        self.fake_handler = FakeDialHandler()
        hc = {"handler": self.fake_handler, "config": FakeConfig()}
        return tornado.web.Application(server.make_routes(hc))

    def _upload(self, body, query=''):
        response = self.fetch(
            f"/api/v0/dial/ABC123/image/set?key=testkey{query}", method='POST', body=_multipart(body),
            headers={'Content-Type': f'multipart/form-data; boundary={BOUNDARY}'})
        return response, json.loads(response.body)

    def test_new_image_replaces_the_stored_one(self):
        (self.upload_dir / 'img_ABC123').write_bytes(b'old')

        response, _ = self._upload(b'new')

        assert response.code == 201
        assert (self.upload_dir / 'img_ABC123').read_bytes() == b'new'
        assert sorted(p.name for p in self.upload_dir.iterdir()) == ['img_ABC123', 'img_blank']
        assert self.fake_handler.images == [('ABC123', str(self.upload_dir / 'img_ABC123'))]

    def test_identical_image_is_skipped_without_a_temp_file(self):
        (self.upload_dir / 'img_ABC123').write_bytes(b'same')

        response, body = self._upload(b'same')

        assert response.code == 200
        assert 'Skipping' in body['message']
        assert sorted(p.name for p in self.upload_dir.iterdir()) == ['img_ABC123', 'img_blank']
        assert self.fake_handler.images == []

    def test_force_resends_an_identical_image(self):
        (self.upload_dir / 'img_ABC123').write_bytes(b'same')

        response, _ = self._upload(b'same', '&force=true')

        assert response.code == 201
        assert len(self.fake_handler.images) == 1

    def test_missing_imgfile_is_503(self):
        response = self.fetch("/api/v0/dial/ABC123/image/set?key=testkey", method='POST', body=b'')
        assert response.code == 503
        assert self.fake_handler.images == []

    def test_crc_matches_the_uploaded_bytes(self):
        self._upload(b'pixels')

        response = self.fetch("/api/v0/dial/ABC123/image/crc?key=testkey")

        assert json.loads(response.body)['data'] == "%08X" % zlib.crc32(b'pixels')

    def test_get_falls_back_to_blank(self):
        response = self.fetch("/api/v0/dial/ABC123/image/get?key=testkey")

        assert response.code == 200
        assert response.body == b'blank'
