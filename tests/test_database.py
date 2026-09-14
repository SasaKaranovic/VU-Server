import os
import pytest

from database import DialsDB


@pytest.fixture
def db(tmp_path):
    db_file = str(tmp_path / "test_vudials.db")
    return DialsDB(database_file=db_file, init_if_missing=True)


def test_dial_update_cell_does_not_allow_sql_injection_via_value(db):
    # Two innocent dials in the DB.
    db.fetch_dial_info_or_create_default('AAAAAAAAAAAA', 'Dial A')
    db.fetch_dial_info_or_create_default('BBBBBBBBBBBB', 'Dial B')

    # A value crafted to break out of the SET clause and neuter the WHERE
    # clause, so it updates every row instead of just the targeted dial.
    payload = "PWNED' WHERE '1'='1"
    db.dial_update_cell(dial_uid='AAAAAAAAAAAA', cell='dial_name', value=payload)

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
    key_a = db.api_key_generate(key_name='Key A', level=1)
    key_b = db.api_key_generate(key_name='Key B', level=1)

    payload = "PWNED' WHERE '1'='1"
    db.api_key_update(key_uid=key_a, key_name=payload)

    keys = db.api_key_list()

    assert keys[key_a]['key_name'] == payload
    assert keys[key_b]['key_name'] == 'Key B'


def test_api_key_delete_returns_false_for_nonexistent_key(db):
    assert db.api_key_delete('does-not-exist') is False


def test_api_key_delete_without_dial_access_reports_success(db):
    # A freshly generated key has no rows in `dial_access`. Deleting it must
    # still report success -- the old code returned the result of a *second*
    # `_more_than_one_changed()` check that only saw the (empty) dial_access
    # delete, so it wrongly returned False even though the key was removed.
    key = db.api_key_generate(key_name='Temp key', level=1)
    assert db.api_key_get_id(key) is not None

    assert db.api_key_delete(key) is True
    assert db.api_key_get_id(key) is None


def test_api_key_delete_with_dial_access_reports_success(db):
    key = db.api_key_generate(key_name='Temp key', level=1)
    db.api_key_add_dial_access(key, ['AAAAAAAAAAAA'])

    assert db.api_key_delete(key) is True
    assert db.api_key_get_id(key) is None
