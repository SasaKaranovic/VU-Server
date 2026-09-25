import re
import sqlite3

import pytest

from database import DialsDB


@pytest.fixture
def db(tmp_path):
    db_file = str(tmp_path / "test_vudials.db")
    return DialsDB(database_file=db_file)


def test_dial_update_cell_does_not_allow_sql_injection_via_value(db):
    # Two innocent dials in the DB.
    db.fetch_dial_info_or_create_default('AAAAAAAAAAAA', 'Dial A')
    db.fetch_dial_info_or_create_default('BBBBBBBBBBBB', 'Dial B')

    # A value crafted to break out of the SET clause and neuter the WHERE
    # clause, so it updates every row instead of just the targeted dial.
    payload = "PWNED' WHERE '1'='1"
    db.dial_update_cell_with_dict('AAAAAAAAAAAA', {'dial_name': payload})

    dial_a = db.fetch_dial_info_or_create_default('AAAAAAAAAAAA')
    dial_b = db.fetch_dial_info_or_create_default('BBBBBBBBBBBB')

    assert dial_a['dial_name'] == payload
    # The untargeted dial must be unaffected if the query is safe.
    assert dial_b['dial_name'] == 'Dial B'


def test_dial_update_cell_with_dict_does_not_allow_sql_injection_via_value(db):
    db.fetch_dial_info_or_create_default('AAAAAAAAAAAA', 'Dial A')
    db.fetch_dial_info_or_create_default('BBBBBBBBBBBB', 'Dial B')

    payload = "9999' WHERE '1'='1"
    db.dial_update_cell_with_dict('AAAAAAAAAAAA', {'easing_backlight_step': payload})

    dial_a = db.fetch_dial_info_or_create_default('AAAAAAAAAAAA')
    dial_b = db.fetch_dial_info_or_create_default('BBBBBBBBBBBB')

    assert dial_a['easing_backlight_step'] == payload
    assert dial_b['easing_backlight_step'] != payload


def test_api_key_update_does_not_allow_sql_injection_via_key_name(db):
    key_a = db.api_key_generate(key_name='Key A')
    key_b = db.api_key_generate(key_name='Key B')

    payload = "PWNED' WHERE '1'='1"
    db.api_key_update(key_uid=key_a, key_name=payload)

    keys = db.api_key_list()

    assert keys[key_a]['key_name'] == payload
    assert keys[key_b]['key_name'] == 'Key B'


def test_api_key_delete_returns_false_for_nonexistent_key(db):
    assert db.api_key_delete('does-not-exist') is False


def test_api_key_delete_without_dial_access_reports_success(db):
    # A freshly generated key has no rows in `dial_access`.
    key = db.api_key_generate(key_name='Temp key')
    assert db.api_key_get_id(key) is not None

    assert db.api_key_delete(key) is True
    assert db.api_key_get_id(key) is None


def test_api_key_delete_with_dial_access_reports_success(db):
    key = db.api_key_generate(key_name='Temp key')
    db.api_key_add_dial_access(key, ['AAAAAAAAAAAA'])

    assert db.api_key_delete(key) is True
    assert db.api_key_get_id(key) is None


def test_api_key_delete_removes_dial_access(db):
    key = db.api_key_generate(key_name='Temp key')
    key_id = db.api_key_get_id(key)
    db.api_key_add_dial_access(key, ['AAAAAAAAAAAA', 'BBBBBBBBBBBB'])

    db.api_key_delete(key)
    assert db.api_key_get_dial_access(key_id) == []


def test_api_key_delete_refuses_master_key(db):
    db.api_update_master('MASTERKEY123')

    assert db.api_key_delete('MASTERKEY123') is False
    assert db.api_key_get_id('MASTERKEY123') == 1


def test_generated_api_keys_use_expected_alphabet_and_length(db):
    keys = {db.api_key_generate(key_name=f'Key {i}') for i in range(20)}

    assert len(keys) == 20
    for key in keys:
        assert re.fullmatch(r'[a-km-np-z0-9]{16}', key)


def test_api_key_update_is_committed(db):
    key = db.api_key_generate(key_name='Old name')
    assert db.api_key_update(key, 'New name') is True

    # A new connection only sees committed rows.
    verify = sqlite3.connect(db.database_file)
    row = verify.execute("SELECT key_name FROM api_keys WHERE key_uid=?", (key,)).fetchone()
    verify.close()
    assert row[0] == 'New name'


def test_api_key_update_unknown_key_returns_false(db):
    assert db.api_key_update('does-not-exist', 'Name') is False


def test_fetch_dial_info_keeps_existing_row(db):
    db.fetch_dial_info_or_create_default('AAAAAAAAAAAA', 'Dial A')
    dial = db.fetch_dial_info_or_create_default('AAAAAAAAAAAA', 'Other name')

    assert dial['dial_name'] == 'Dial A'


def test_dial_update_cell_reports_missing_dial(db):
    assert db.dial_update_cell_with_dict('NOSUCHDIAL', {'dial_name': 'x'}) is False
    db.fetch_dial_info_or_create_default('AAAAAAAAAAAA')
    assert db.dial_update_cell_with_dict('AAAAAAAAAAAA', {'dial_name': 'x'}) is True


def test_api_key_add_dial_access_replaces_existing(db):
    key = db.api_key_generate(key_name='Temp key')
    db.api_key_add_dial_access(key, ['AAAAAAAAAAAA', 'BBBBBBBBBBBB'])

    assert db.api_key_add_dial_access(key, ['CCCCCCCCCCCC']) is True
    assert db.api_key_list()[key]['dials'] == ['CCCCCCCCCCCC']


def test_existing_database_file_opens_unchanged(tmp_path):
    db_file = str(tmp_path / "existing.db")
    DialsDB(database_file=db_file).api_update_master('MASTERKEY123')

    reopened = DialsDB(database_file=db_file)
    assert reopened.api_key_list()['MASTERKEY123']['priviledges'] == 99


def test_api_key_generate_redraws_on_collision(db):
    existing = db.api_key_generate(key_name='Existing')
    draws = iter([existing, 'freshkey12345678'])
    db.generate_api_key_str = lambda: next(draws)

    assert db.api_key_generate(key_name='New') == 'freshkey12345678'


def test_api_update_master_is_committed(db):
    db.api_update_master('MASTERKEY123')

    # A new connection only sees committed rows.
    verify = sqlite3.connect(db.database_file)
    row = verify.execute("SELECT key_uid FROM api_keys WHERE key_name='MASTER_KEY'").fetchone()
    verify.close()
    assert row == ('MASTERKEY123',)
