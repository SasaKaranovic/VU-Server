import pytest

import server_config
from database import DialsDB
from server_config import ServerConfig


@pytest.fixture
def make_config(tmp_path, monkeypatch):
    monkeypatch.setattr(server_config.db, 'DialsDB',
                        lambda **_: DialsDB(database_file=str(tmp_path / "vudials.db")))

    def _make(text):
        path = tmp_path / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return ServerConfig(str(path))
    return _make


def test_missing_keys_take_defaults_and_extra_keys_load(make_config):
    config = make_config("server:\n  master_key: abc\n  communication_timeout: 10\nhardware:\n")

    assert config.server['port'] == 5340
    assert config.server['dial_update_period'] == 200
    assert config.server['hostname'] == 'localhost'
    assert config.server['communication_timeout'] == 10
    assert config.hardware == {'port': None}


def test_empty_hostname_means_all_interfaces(make_config):
    config = make_config("server:\n  hostname:\n  master_key: abc\n")

    assert config.server['hostname'] == ''


def test_invalid_file_uses_defaults(make_config):
    config = make_config("- not a mapping\n")

    assert config.server == server_config.SERVER_DEFAULTS
    assert config.hardware == server_config.HARDWARE_DEFAULTS


def test_empty_master_key_is_rejected(make_config):
    with pytest.raises(ValueError):
        make_config("server:\n  master_key:\n")


def test_only_configured_master_key_is_admin(make_config):
    config = make_config("server:\n  master_key: abc\n")
    user_key = config.create_api_key('user')
    config.api_key_add_dial_access(user_key, ['AAA'])

    assert config.validate_admin_key('abc')
    assert not config.validate_admin_key(user_key)
    assert not config.validate_admin_key(None)
    assert config.api_key_has_access_to_dial('abc', 'BBB')
    assert config.api_key_has_access_to_dial(user_key, 'AAA')
    assert not config.api_key_has_access_to_dial(user_key, 'BBB')
    assert not config.api_key_has_access_to_dial('nope', 'AAA')


def test_key_rename_is_visible_without_reload(make_config):
    config = make_config("server:\n  master_key: abc\n")
    key = config.create_api_key('old')

    config.update_api_key(key, 'new')

    assert config.list_keys()[key]['key_name'] == 'new'
