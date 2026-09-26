import pytest

import server_config
from database import DialsDB
from server_config import ServerConfig


VALID_CONFIG = """\
server:
  hostname: localhost
  port: 5340
  communication_timeout: 10
  master_key: TESTMASTERKEY

hardware:
  port:
"""


@pytest.fixture
def make_config(tmp_path, monkeypatch):
    """Build a ServerConfig from YAML text, backed by a throwaway database."""
    db_file = str(tmp_path / "config_test.db")
    monkeypatch.setattr(server_config.db, 'DialsDB',
                        lambda **_: DialsDB(database_file=db_file, init_if_missing=True))
    monkeypatch.setattr(server_config, 'show_error_msg', lambda *a, **k: None)
    monkeypatch.setattr(server_config, 'show_warning_msg', lambda *a, **k: None)

    def _make(yaml_text=VALID_CONFIG):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_text, encoding="utf-8")
        return ServerConfig(str(config_file))
    return _make


def test_update_api_key_refreshes_key_list(make_config):
    config = make_config()
    key = config.create_api_key('Old name', 1)

    assert config.update_api_key(key, 'New name') is True
    assert config.list_keys()[key]['key_name'] == 'New name'
